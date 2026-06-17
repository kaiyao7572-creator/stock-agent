"""
Technical indicator calculations.

Uses the `ta` library (Technical Analysis Library in Python) on top of
OHLCV data fetched from Polygon or Finnhub candles.

Returned as a TechnicalSnapshot dataclass.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import httpx
import pandas as pd
import ta

from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class TechnicalSnapshot:
    ticker: str

    sma_20:          Optional[float] = None
    sma_50:          Optional[float] = None
    sma_200:         Optional[float] = None

    rsi:             Optional[float] = None   # 0–100
    macd:            Optional[float] = None
    macd_signal:     Optional[float] = None
    macd_hist:       Optional[float] = None

    volume_ratio:    Optional[float] = None   # today / avg
    trend_direction: str = "neutral"          # bullish / bearish / neutral
    trend_strength:  float = 0.0              # 0–100


async def _get_candles_polygon(ticker: str, days: int = 250) -> pd.DataFrame:
    """Fetch daily OHLCV from Polygon (requires paid tier for full history)."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=days * 2)
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": days,
              "apiKey": settings.polygon_api_key}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise ValueError(f"No candle data from Polygon for {ticker}")
    df = pd.DataFrame(results)
    df.rename(columns={"o": "open", "h": "high", "l": "low",
                        "c": "close", "v": "volume", "t": "timestamp"}, inplace=True)
    return df


async def _get_candles_finnhub(ticker: str, days: int = 250) -> pd.DataFrame:
    import time
    now   = int(time.time())
    start = now - days * 86400
    url   = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": ticker, "resolution": "D",
               "from": start, "to": now, "token": settings.finnhub_api_key}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()
    data = r.json()
    if data.get("s") != "ok":
        raise ValueError(f"Finnhub candle status: {data.get('s')}")
    df = pd.DataFrame({
        "close":  data["c"],
        "high":   data["h"],
        "low":    data["l"],
        "open":   data["o"],
        "volume": data["v"],
        "timestamp": data["t"],
    })
    return df


def _compute_indicators(df: pd.DataFrame, ticker: str) -> TechnicalSnapshot:
    close  = df["close"]
    volume = df["volume"]

    snap = TechnicalSnapshot(ticker=ticker)

    # SMAs
    if len(close) >= 20:
        snap.sma_20  = float(close.rolling(20).mean().iloc[-1])
    if len(close) >= 50:
        snap.sma_50  = float(close.rolling(50).mean().iloc[-1])
    if len(close) >= 200:
        snap.sma_200 = float(close.rolling(200).mean().iloc[-1])

    # RSI
    if len(close) >= 15:
        snap.rsi = float(ta.momentum.RSIIndicator(close).rsi().iloc[-1])

    # MACD
    if len(close) >= 35:
        macd_obj = ta.trend.MACD(close)
        snap.macd        = float(macd_obj.macd().iloc[-1])
        snap.macd_signal = float(macd_obj.macd_signal().iloc[-1])
        snap.macd_hist   = float(macd_obj.macd_diff().iloc[-1])

    # Volume ratio (latest vs 20-day avg)
    if len(volume) >= 20:
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        snap.volume_ratio = float(volume.iloc[-1]) / avg_vol if avg_vol else 0.0

    # Trend direction and strength
    price = float(close.iloc[-1])
    bullish_signals = 0
    total_signals   = 0

    for sma in [snap.sma_20, snap.sma_50, snap.sma_200]:
        if sma is not None:
            total_signals += 1
            if price > sma:
                bullish_signals += 1

    if snap.macd_hist is not None:
        total_signals += 1
        if snap.macd_hist > 0:
            bullish_signals += 1

    if total_signals:
        ratio = bullish_signals / total_signals
        if ratio >= 0.75:
            snap.trend_direction = "bullish"
            snap.trend_strength  = ratio * 100
        elif ratio <= 0.25:
            snap.trend_direction = "bearish"
            snap.trend_strength  = (1 - ratio) * 100
        else:
            snap.trend_direction = "neutral"
            snap.trend_strength  = 50.0

    return snap


async def get_technical_snapshot(ticker: str) -> TechnicalSnapshot:
    """Fetch candles and compute all indicators; falls back between providers."""
    providers = []
    if settings.polygon_api_key:
        providers.append(("polygon",  _get_candles_polygon))
    if settings.finnhub_api_key:
        providers.append(("finnhub",  _get_candles_finnhub))

    last_error = None
    for name, fetch_fn in providers:
        try:
            df   = await fetch_fn(ticker)
            snap = _compute_indicators(df, ticker)
            logger.info("Technicals for %s via %s", ticker, name)
            return snap
        except Exception as exc:
            logger.warning("Candle provider %s failed for %s: %s", name, ticker, exc)
            last_error = exc

    # Return empty snapshot if all providers fail rather than crashing the pipeline
    logger.error("Could not fetch candles for %s: %s", ticker, last_error)
    return TechnicalSnapshot(ticker=ticker)
