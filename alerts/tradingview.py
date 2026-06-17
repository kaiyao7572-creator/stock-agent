"""
Handles inbound TradingView webhook alerts.

TradingView alert message (JSON body):
{
    "ticker":   "{{ticker}}",
    "close":    "{{close}}",
    "volume":   "{{volume}}",
    "interval": "{{interval}}"
}

The handler validates the payload and queues an analysis run.
We intentionally do NOT trigger analysis synchronously — we enqueue and
return 200 immediately so TradingView's webhook times out don't pile up.
"""

import asyncio
import logging
import re
from datetime import datetime

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)
TICKER_RE = re.compile(r"^[A-Z0-9.-]{1,10}$")

# Simple in-memory queue; replace with Redis/RabbitMQ for production scale
_alert_queue: asyncio.Queue = asyncio.Queue(maxsize=500)


class TradingViewPayload(BaseModel):
    ticker: str
    close: float
    volume: float
    interval: str = "D"

    @field_validator("ticker", mode="before")
    @classmethod
    def normalise_ticker(cls, v: str) -> str:
        ticker = v.strip().upper()
        if not TICKER_RE.fullmatch(ticker):
            raise ValueError("Ticker must be 1-10 chars: A-Z, 0-9, dot, or dash.")
        return ticker

    @field_validator("close", "volume", mode="before")
    @classmethod
    def coerce_numeric(cls, v):
        value = float(v)
        if value < 0:
            raise ValueError("Value must be non-negative.")
        return value


class AlertEvent:
    """Rich event pushed onto the queue."""
    def __init__(self, payload: TradingViewPayload):
        self.ticker    = payload.ticker
        self.close     = payload.close
        self.volume    = payload.volume
        self.interval  = payload.interval
        self.received  = datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"<AlertEvent {self.ticker} close={self.close} "
            f"vol={self.volume} @{self.received.isoformat()}>"
        )


async def enqueue_alert(payload: TradingViewPayload) -> bool:
    """
    Push alert onto the internal queue.
    Returns False if the queue is full (back-pressure signal).
    """
    event = AlertEvent(payload)
    try:
        _alert_queue.put_nowait(event)
        logger.info("Enqueued alert: %s", event)
        return True
    except asyncio.QueueFull:
        logger.warning("Alert queue full — dropping %s", payload.ticker)
        return False


async def get_alert_queue() -> asyncio.Queue:
    return _alert_queue
