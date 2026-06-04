"""
Market data layer.

Priority order:
  1. Finnhub  — real-time quote + fundamentals
  2. Polygon  — richer historical data
  3. Alpha Vantage — last-resort fallback (slower, rate-limited)

All public functions return a MarketSnapshot dataclass or raise DataError.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


class DataError(Exception):
    """Raised when no provider can satisfy the request."""


@dataclass
class MarketSnapshot:
    ticker: str

    # Price
    current_price:  float = 0.0
    week_52_high:   float = 0.0
    week_52_low:    float = 0.0
    market_cap:     float = 0.0

    # Volume
    volume:         float = 0.0
    avg_volume:     float = 0.0

    # Valuation
    pe_ratio:       float = 0.0
    eps:            float = 0.0

    # Growth
    revenue_growth: float = 0.0   # YoY %
    profit_growth:  float = 0.0   # YoY %

    # Balance sheet
    debt_to_equity: float = 0.0
    free_cash_flow: float = 0.0

    # Ownership
    institutional_ownership: float = 0.0

    # Meta
    source: str = "unknown"
    errors: list = field(default_factory=list)


# ── Finnhub ──────────────────────────────────────────────────────────────────

async def _finnhub_quote(ticker: str, client: httpx.AsyncClient) -> dict:
    url = "https://finnhub.io/api/v1/quote"
    r   = await client.get(url, params={"symbol": ticker, "token": settings.finnhub_api_key})
    r.raise_for_status()
    return r.json()


async def _finnhub_fundamentals(ticker: str, client: httpx.AsyncClient) -> dict:
    url = "https://finnhub.io/api/v1/stock/metric"
    r   = await client.get(
        url,
        params={"symbol": ticker, "metric": "all", "token": settings.finnhub_api_key},
    )
    r.raise_for_status()
    return r.json().get("metric", {})


async def _fetch_from_finnhub(ticker: str) -> MarketSnapshot:
    async with httpx.AsyncClient(timeout=10) as client:
        quote  = await _finnhub_quote(ticker, client)
        metric = await _finnhub_fundamentals(ticker, client)

    snap = MarketSnapshot(ticker=ticker, source="finnhub")
    snap.current_price  = float(quote.get("c") or 0)
    snap.week_52_high   = float(metric.get("52WeekHigh") or 0)
    snap.week_52_low    = float(metric.get("52WeekLow")  or 0)
    snap.market_cap     = float(metric.get("marketCapitalization") or 0) * 1e6
    snap.pe_ratio       = float(metric.get("peBasicExclExtraTTM") or 0)
    snap.eps            = float(metric.get("epsBasicExclExtraItemsTTM") or 0)
    snap.revenue_growth = float(metric.get("revenueGrowthTTMYoy") or 0)
    snap.profit_growth  = float(metric.get("netProfitMarginAnnual") or 0)
    snap.debt_to_equity = float(metric.get("totalDebt/totalEquityAnnual") or 0)
    snap.free_cash_flow = float(metric.get("freeCashFlowAnnual") or 0) * 1e6
    snap.institutional_ownership = float(metric.get("institutionalOwnershipPercentage") or 0)
    return snap


# ── Polygon ───────────────────────────────────────────────────────────────────

async def _fetch_from_polygon(ticker: str) -> MarketSnapshot:
    base = "https://api.polygon.io"
    headers = {"Authorization": f"Bearer {settings.polygon_api_key}"}

    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        snap_r  = await client.get(f"{base}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
        detail_r = await client.get(f"{base}/v3/reference/tickers/{ticker}")

    snap_r.raise_for_status()
    detail_r.raise_for_status()

    snap_data = snap_r.json().get("ticker", {})
    day        = snap_data.get("day", {})
    results    = detail_r.json().get("results", {})

    snap = MarketSnapshot(ticker=ticker, source="polygon")
    snap.current_price = float(day.get("c") or 0)
    snap.volume        = float(day.get("v") or 0)
    snap.market_cap    = float(results.get("market_cap") or 0)
    return snap


# ── Alpha Vantage fallback ────────────────────────────────────────────────────

async def _fetch_from_alpha_vantage(ticker: str) -> MarketSnapshot:
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol":   ticker,
        "apikey":   settings.alpha_vantage_api_key,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()
    data = r.json()

    snap = MarketSnapshot(ticker=ticker, source="alpha_vantage")
    snap.market_cap     = float(data.get("MarketCapitalization") or 0)
    snap.pe_ratio       = float(data.get("PERatio") or 0)
    snap.eps            = float(data.get("EPS") or 0)
    snap.week_52_high   = float(data.get("52WeekHigh") or 0)
    snap.week_52_low    = float(data.get("52WeekLow")  or 0)
    snap.debt_to_equity = float(data.get("DebtToEquityRatio") or 0)
    return snap


# ── Public API ────────────────────────────────────────────────────────────────

async def get_market_snapshot(ticker: str) -> MarketSnapshot:
    """
    Try providers in order; return first successful result.
    Raises DataError only if ALL providers fail.
    """
    providers = []

    if settings.finnhub_api_key:
        providers.append(("finnhub",       _fetch_from_finnhub))
    if settings.polygon_api_key:
        providers.append(("polygon",       _fetch_from_polygon))
    if settings.alpha_vantage_api_key:
        providers.append(("alpha_vantage", _fetch_from_alpha_vantage))

    if not providers:
        raise DataError("No market data API keys configured.")

    last_error: Optional[Exception] = None
    for name, fetch_fn in providers:
        try:
            snap = await fetch_fn(ticker)
            logger.info("Market snapshot for %s from %s", ticker, name)
            return snap
        except Exception as exc:
            logger.warning("Provider %s failed for %s: %s", name, ticker, exc)
            last_error = exc

    raise DataError(f"All providers failed for {ticker}: {last_error}")
