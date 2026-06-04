"""
Daily scanner — the core pipeline.

Runs every night (default 11 PM via APScheduler).
For each ticker in the watch-list:
  1. Fetch market data
  2. Fetch technical data
  3. Fetch news
  4. Calculate scores
  5. Generate AI analysis
  6. Persist to DB
  7. Update performance tracking records that are now due (7d/30d/90d)

Also exposes `run_single_ticker()` for on-demand webhook-triggered analyses.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from config import get_settings
from database.database import get_session
from database.models   import Analysis, PerformanceTracking, Stock
from data.market       import get_market_snapshot
from data.technicals   import get_technical_snapshot
from data.news         import get_news_snapshot
from scoring.ranking   import calculate_scores
from ai.cerebras_client import complete
from ai.prompts         import build_analysis_prompt
from integrations.discord_bot import send_analysis_alert
from reports.generator  import generate_daily_report
from integrations.discord_bot import send_daily_report

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── S&P 500 ticker list (abbreviated; replace with full list or DB-driven) ───

SP500_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "BRK.B",
    "UNH",  "JNJ",  "XOM",  "JPM",   "V",    "PG",   "MA",   "HD",
    "CVX",  "MRK",  "ABBV", "AVGO",  "PEP",  "COST", "KO",   "WMT",
    "ADBE", "MCD",  "CRM",  "ACN",   "LLY",  "TMO",  "CSCO", "NEE",
    "NKE",  "ORCL", "QCOM", "AMD",   "HON",  "UPS",  "AMGN", "MS",
]


def _extract_section(text: str, header: str) -> str:
    """Pull text between two markdown headers."""
    pattern = rf"###\s*{re.escape(header)}.*?\n(.*?)(?=###|\Z)"
    match   = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _extract_confidence(text: str) -> Optional[float]:
    """Find the first integer after '### 7. Confidence Score'."""
    section = _extract_section(text, "7. Confidence Score")
    m = re.search(r"\b(\d{1,3})\b", section)
    return float(m.group(1)) if m else None


async def run_single_ticker(ticker: str) -> Optional[dict]:
    """
    Full pipeline for one ticker.
    Returns persisted analysis dict or None on hard failure.
    """
    ticker = ticker.upper().strip()
    logger.info("▶ Analysing %s", ticker)

    try:
        market = await get_market_snapshot(ticker)
        tech   = await get_technical_snapshot(ticker)
        news   = await get_news_snapshot(ticker)
    except Exception as exc:
        logger.error("Data fetch failed for %s: %s", ticker, exc)
        return None

    scores = calculate_scores(market, tech, news)

    # Build AI prompt
    market_dict = {
        "Current Price":            market.current_price,
        "52 Week High":             market.week_52_high,
        "52 Week Low":              market.week_52_low,
        "Market Cap ($)":           market.market_cap,
        "Volume":                   market.volume,
        "Avg Volume":               market.avg_volume,
        "P/E Ratio":                market.pe_ratio,
        "EPS":                      market.eps,
        "Revenue Growth (YoY)":     market.revenue_growth,
        "Profit Growth":            market.profit_growth,
        "Debt to Equity":           market.debt_to_equity,
        "Free Cash Flow ($)":       market.free_cash_flow,
        "Institutional Ownership %":market.institutional_ownership,
    }
    tech_dict = {
        "SMA 20":          tech.sma_20,
        "SMA 50":          tech.sma_50,
        "SMA 200":         tech.sma_200,
        "RSI":             tech.rsi,
        "MACD":            tech.macd,
        "MACD Signal":     tech.macd_signal,
        "MACD Histogram":  tech.macd_hist,
        "Volume Ratio":    tech.volume_ratio,
        "Trend Direction": tech.trend_direction,
        "Trend Strength":  tech.trend_strength,
    }
    news_dict = {
        "News Score":      news.score,
        "Positive Items":  news.positive,
        "Neutral Items":   news.neutral,
        "Negative Items":  news.negative,
        "Top Headline":    news.items[0].headline if news.items else "No news",
    }

    sys_prompt, user_prompt = build_analysis_prompt(
        ticker        = ticker,
        market_data   = market_dict,
        technical_data= tech_dict,
        news_data     = news_dict,
        scores        = scores.as_dict(),
    )

    try:
        analysis_text = await complete(sys_prompt, user_prompt)
    except Exception as exc:
        logger.error("Cerebras analysis failed for %s: %s", ticker, exc)
        analysis_text = f"ERROR: {exc}"

    bull_case    = _extract_section(analysis_text, "5. Bull Case")
    bear_case    = _extract_section(analysis_text, "6. Bear Case")
    ai_conf      = _extract_confidence(analysis_text)
    confidence   = ai_conf if ai_conf is not None else scores.confidence

    # Persist ────────────────────────────────────────────────────────────────
    async with get_session() as db:
        # Upsert stock record
        stmt = select(Stock).where(Stock.ticker == ticker)
        stock_row = (await db.execute(stmt)).scalar_one_or_none()
        if not stock_row:
            stock_row = Stock(ticker=ticker)
            db.add(stock_row)

        analysis = Analysis(
            ticker          = ticker,
            revenue_score   = scores.revenue_score,
            earnings_score  = scores.earnings_score,
            trend_score     = scores.trend_score,
            volume_score    = scores.volume_score,
            news_score      = scores.news_score,
            health_score    = scores.health_score,
            final_score     = scores.final_score,
            confidence      = confidence,
            bull_case       = bull_case,
            bear_case       = bear_case,
            analysis_text   = analysis_text,
        )
        db.add(analysis)
        await db.flush()   # get analysis.id

        tracking = PerformanceTracking(
            ticker         = ticker,
            analysis_id    = analysis.id,
            starting_price = market.current_price,
        )
        db.add(tracking)

    logger.info("✅ %s — score %.1f | conf %.0f%%", ticker, scores.final_score, confidence)

    # Notify Discord (fire and forget)
    asyncio.create_task(send_analysis_alert(
        ticker       = ticker,
        final_score  = scores.final_score,
        confidence   = confidence,
        bull_case    = bull_case,
        bear_case    = bear_case,
    ))

    return {
        "ticker":        ticker,
        "final_score":   scores.final_score,
        "confidence":    confidence,
        "bull_case":     bull_case,
        "bear_case":     bear_case,
        "analysis_text": analysis_text,
        "scores":        scores.as_dict(),
    }


async def _update_performance_records() -> None:
    """
    Look for PerformanceTracking rows where price_7d / price_30d / price_90d
    are still NULL and the time threshold has passed; fill them in.
    """
    now = datetime.utcnow()

    async with get_session() as db:
        stmt = select(PerformanceTracking).where(
            PerformanceTracking.starting_price.isnot(None)
        )
        rows = (await db.execute(stmt)).scalars().all()

    for row in rows:
        age = (now - row.analysis_date).days if row.analysis_date else 0
        ticker = row.ticker

        try:
            if age >= 7 and row.price_7d is None:
                snap = await get_market_snapshot(ticker)
                async with get_session() as db:
                    rec = await db.get(PerformanceTracking, row.id)
                    if rec:
                        rec.price_7d    = snap.current_price
                        rec.return_7d   = (snap.current_price - rec.starting_price) / rec.starting_price * 100 if rec.starting_price else None

            if age >= 30 and row.price_30d is None:
                snap = await get_market_snapshot(ticker)
                async with get_session() as db:
                    rec = await db.get(PerformanceTracking, row.id)
                    if rec:
                        rec.price_30d   = snap.current_price
                        rec.return_30d  = (snap.current_price - rec.starting_price) / rec.starting_price * 100 if rec.starting_price else None

            if age >= 90 and row.price_90d is None:
                snap = await get_market_snapshot(ticker)
                async with get_session() as db:
                    rec = await db.get(PerformanceTracking, row.id)
                    if rec:
                        rec.price_90d   = snap.current_price
                        rec.return_90d  = (snap.current_price - rec.starting_price) / rec.starting_price * 100 if rec.starting_price else None
        except Exception as exc:
            logger.warning("Performance update failed for %s: %s", ticker, exc)


async def run_daily_scan(tickers: list[str] = None) -> None:
    """
    Full nightly scan:  iterate tickers → analyse → report → Discord.
    Pass custom ticker list for testing; defaults to SP500_TICKERS.
    """
    tickers = tickers or SP500_TICKERS
    logger.info("🌙 Daily scan started — %d tickers", len(tickers))

    # Concurrency-limited analysis (avoid hammering APIs)
    semaphore = asyncio.Semaphore(5)

    async def _guarded(t: str):
        async with semaphore:
            return await run_single_ticker(t)

    results = await asyncio.gather(*[_guarded(t) for t in tickers], return_exceptions=True)

    ok    = [r for r in results if isinstance(r, dict)]
    errs  = [r for r in results if isinstance(r, Exception)]
    logger.info("Daily scan complete — %d OK, %d errors", len(ok), len(errs))

    # Update 7d/30d/90d tracking
    await _update_performance_records()

    # Generate and send report
    report = await generate_daily_report(top_n=settings.top_n_stocks)
    await send_daily_report(report["top_stocks"])
    logger.info("📊 Daily report sent.")
