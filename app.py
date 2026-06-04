"""
FastAPI application entry point.

Routes:
  POST /webhook/tradingview  — receives TradingView alerts
  GET  /analysis/{ticker}    — latest analysis for a ticker
  GET  /top-stocks           — top N by final_score
  GET  /report/daily         — today's daily report
  GET  /health               — liveness check
  GET  /metrics              — historical accuracy stats
"""
from fastapi import Header, HTTPException, Depends
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, select

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings
from database.database import init_db, get_session
from database.models   import Analysis, PerformanceTracking, Stock
from alerts.tradingview import TradingViewPayload, enqueue_alert, get_alert_queue
from reports.generator  import generate_daily_report
from scheduler.daily_scan import run_single_ticker, run_daily_scan

API_KEY = "123"

def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API Key"
        )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Scheduler ────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


async def _alert_consumer() -> None:
    """Background task that drains the TradingView alert queue."""
    queue = await get_alert_queue()
    while True:
        event = await queue.get()
        logger.info("Processing queued alert: %s", event)
        asyncio.create_task(run_single_ticker(event.ticker))
        queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    asyncio.create_task(_alert_consumer())

    # Schedule nightly scan at 23:00 UTC
    scheduler.add_job(run_daily_scan, "cron", hour=23, minute=0,
                      id="daily_scan", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started.")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Stock Research Agent",
    description="Research assistant: ranks stocks, explains reasoning, tracks accuracy.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Response helpers ──────────────────────────────────────────────────────────

def _analysis_to_dict(row: Analysis) -> dict[str, Any]:
    return {
        "ticker":         row.ticker,
        "timestamp":      row.timestamp.isoformat() if row.timestamp else None,
        "revenue_score":  row.revenue_score,
        "earnings_score": row.earnings_score,
        "trend_score":    row.trend_score,
        "volume_score":   row.volume_score,
        "news_score":     row.news_score,
        "health_score":   row.health_score,
        "final_score":    row.final_score,
        "confidence":     row.confidence,
        "bull_case":      row.bull_case,
        "bear_case":      row.bear_case,
        "analysis_text":  row.analysis_text,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook/tradingview")
async def tradingview_webhook(payload: TradingViewPayload):
    """
    Receive TradingView alert.  Enqueues analysis and returns 200 immediately.
    """
    ok = await enqueue_alert(payload)
    if not ok:
        raise HTTPException(status_code=503, detail="Alert queue full. Retry later.")
    return {"status": "queued", "ticker": payload.ticker}

from fastapi import Depends
@app.get("/analysis/{ticker}")
async def get_analysis(ticker: str, _=Depends(verify_api_key)):
    """Return the most recent analysis for a ticker."""
    ticker = ticker.upper().strip()
    async with get_session() as db:
        stmt = (
            select(Analysis)
            .where(Analysis.ticker == ticker)
            .order_by(desc(Analysis.timestamp))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail=f"No analysis found for {ticker}")
    return _analysis_to_dict(row)


@app.post("/analysis/{ticker}/refresh")
async def refresh_analysis(ticker: str, background_tasks: BackgroundTasks):
    """Trigger a fresh on-demand analysis (runs in background)."""
    ticker = ticker.upper().strip()
    background_tasks.add_task(run_single_ticker, ticker)
    return {"status": "started", "ticker": ticker}


@app.get("/top-stocks")
async def top_stocks(n: int = 10, since_hours: int = 36):
    """Return the top N stocks by final_score from the last `since_hours`."""
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    async with get_session() as db:
        stmt = (
            select(Analysis)
            .where(Analysis.timestamp >= cutoff)
            .order_by(desc(Analysis.final_score))
            .limit(n)
        )
        rows = (await db.execute(stmt)).scalars().all()

    return [_analysis_to_dict(r) for r in rows]


@app.get("/report/daily")
async def daily_report():
    """Generate and return the daily research report."""
    return await generate_daily_report(top_n=settings.top_n_stocks)


@app.get("/metrics")
async def historical_metrics():
    """Aggregate accuracy metrics across all performance tracking records."""
    async with get_session() as db:
        stmt = select(PerformanceTracking).where(
            PerformanceTracking.return_30d.isnot(None)
        )
        rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return {"message": "No performance data available yet."}

    returns_30d = [r.return_30d for r in rows if r.return_30d is not None]
    avg_return  = sum(returns_30d) / len(returns_30d) if returns_30d else 0
    win_rate    = sum(1 for r in returns_30d if r > 0) / len(returns_30d) * 100 if returns_30d else 0

    return {
        "records_tracked":      len(rows),
        "win_rate_30d_pct":     round(win_rate, 1),
        "avg_return_30d_pct":   round(avg_return, 2),
        "positive_calls":       sum(1 for r in returns_30d if r > 0),
        "negative_calls":       sum(1 for r in returns_30d if r <= 0),
    }
