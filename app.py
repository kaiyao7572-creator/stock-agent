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
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc, select

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get_settings
from database.database import init_db, get_session
from database.models   import Analysis, PerformanceTracking
from alerts.tradingview import TradingViewPayload, enqueue_alert, get_alert_queue
from reports.generator  import generate_daily_report
from scheduler.daily_scan import run_single_ticker, run_daily_scan

TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,10}$")
_rate_limits: dict[tuple[str, str], list[datetime]] = {}


def require_api_key(x_api_key: str = Header(default="")):
    if not settings.app_api_key:
        raise HTTPException(status_code=503, detail="API key auth is not configured.")
    if x_api_key != settings.app_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def validate_ticker(ticker: str) -> str:
    value = ticker.upper().strip()
    if not TICKER_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail="Ticker must be 1-10 chars: A-Z, 0-9, dot, or dash.",
        )
    return value


def rate_limit(bucket: str, limit: int, request: Request) -> None:
    now = datetime.utcnow()
    key = (bucket, request.client.host if request.client else "unknown")
    recent = [ts for ts in _rate_limits.get(key, []) if now - ts < timedelta(minutes=1)]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    recent.append(now)
    _rate_limits[key] = recent

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

    if settings.enable_scheduler:
        scheduler.add_job(
            run_daily_scan,
            CronTrigger.from_crontab(settings.daily_scan_cron),
            id="daily_scan",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started. Ensure this is the only running instance.")
    else:
        logger.info("Scheduler disabled. Set ENABLE_SCHEDULER=true for one instance only.")

    yield

    # Shutdown
    if scheduler.running:
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
    allow_origins=settings.cors_origins,
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


@app.post("/webhook/tradingview", dependencies=[Depends(require_api_key)])
async def tradingview_webhook(payload: TradingViewPayload, request: Request):
    """
    Receive TradingView alert.  Enqueues analysis and returns 200 immediately.
    """
    rate_limit("webhook", settings.webhook_rate_limit_per_minute, request)
    ok = await enqueue_alert(payload)
    if not ok:
        raise HTTPException(status_code=503, detail="Alert queue full. Retry later.")
    return {"status": "queued", "ticker": payload.ticker}


@app.get("/analysis/{ticker}")
async def get_analysis(ticker: str):
    """Return the most recent analysis for a ticker."""
    ticker = validate_ticker(ticker)
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


@app.post("/analysis/{ticker}/refresh", dependencies=[Depends(require_api_key)])
async def refresh_analysis(ticker: str, background_tasks: BackgroundTasks, request: Request):
    """Trigger a fresh on-demand analysis (runs in background)."""
    rate_limit("refresh", settings.refresh_rate_limit_per_minute, request)
    ticker = validate_ticker(ticker)
    background_tasks.add_task(run_single_ticker, ticker)
    return {"status": "started", "ticker": ticker}


@app.get("/top-stocks")
async def top_stocks(
    n: int = Query(default=10, ge=1, le=50),
    since_hours: int = Query(default=36, ge=1, le=168),
):
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
