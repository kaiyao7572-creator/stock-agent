"""
News collection and sentiment scoring.

Sources tried in order:
  1. Finnhub company news
  2. Polygon ticker news

Sentiment is classified as Positive / Neutral / Negative based on
keyword heuristics first; can be upgraded to an ML model without
changing the public interface.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List

import httpx

from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class NewsItem:
    headline: str
    source:   str
    url:      str
    published: str
    sentiment: str  = "neutral"  # positive / neutral / negative


@dataclass
class NewsSnapshot:
    ticker:    str
    items:     List[NewsItem] = field(default_factory=list)
    score:     float = 50.0    # 0–100
    positive:  int   = 0
    neutral:   int   = 0
    negative:  int   = 0


# ── Sentiment keywords ────────────────────────────────────────────────────────

_POS_WORDS = re.compile(
    r"\b(beat|exceed|record|growth|surge|profit|upgraded|outperform|bullish|"
    r"strong|expand|gain|win|boost|positive|revenue|guidance|raise|beat estimates)\b",
    re.IGNORECASE,
)
_NEG_WORDS = re.compile(
    r"\b(miss|loss|decline|layoff|downgrade|underperform|bearish|lawsuit|"
    r"fraud|investigation|warning|recall|debt|bankruptcy|cuts|disappoints|"
    r"missed estimates|lowered guidance)\b",
    re.IGNORECASE,
)


def classify_sentiment(headline: str) -> str:
    pos = len(_POS_WORDS.findall(headline))
    neg = len(_NEG_WORDS.findall(headline))
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


# ── Finnhub news ─────────────────────────────────────────────────────────────

async def _finnhub_news(ticker: str) -> List[NewsItem]:
    today = datetime.utcnow()
    start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end   = today.strftime("%Y-%m-%d")
    url   = "https://finnhub.io/api/v1/company-news"
    params = {"symbol": ticker, "from": start, "to": end,
               "token": settings.finnhub_api_key}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()

    items = []
    for art in r.json()[:20]:
        sentiment = classify_sentiment(art.get("headline", ""))
        items.append(NewsItem(
            headline  = art.get("headline", ""),
            source    = art.get("source", "finnhub"),
            url       = art.get("url", ""),
            published = str(art.get("datetime", "")),
            sentiment = sentiment,
        ))
    return items


# ── Polygon news ──────────────────────────────────────────────────────────────

async def _polygon_news(ticker: str) -> List[NewsItem]:
    url = f"https://api.polygon.io/v2/reference/news"
    params = {"ticker": ticker, "limit": 20,
               "apiKey": settings.polygon_api_key}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()

    items = []
    for art in r.json().get("results", [])[:20]:
        headline  = art.get("title", "")
        sentiment = classify_sentiment(headline)
        items.append(NewsItem(
            headline  = headline,
            source    = "polygon",
            url       = art.get("article_url", ""),
            published = art.get("published_utc", ""),
            sentiment = sentiment,
        ))
    return items


# ── Score calculation ─────────────────────────────────────────────────────────

def _score_items(items: List[NewsItem]) -> float:
    """
    Score = 50 base + (pos - neg) * weight, clamped 0–100.
    Each article contributes proportionally more as count grows (logarithmic).
    """
    if not items:
        return 50.0
    pos = sum(1 for i in items if i.sentiment == "positive")
    neg = sum(1 for i in items if i.sentiment == "negative")
    total = len(items)
    score = 50 + ((pos - neg) / total) * 50
    return max(0.0, min(100.0, score))


# ── Public API ────────────────────────────────────────────────────────────────

async def get_news_snapshot(ticker: str) -> NewsSnapshot:
    items: List[NewsItem] = []

    if settings.finnhub_api_key:
        try:
            items = await _finnhub_news(ticker)
        except Exception as exc:
            logger.warning("Finnhub news failed for %s: %s", ticker, exc)

    if not items and settings.polygon_api_key:
        try:
            items = await _polygon_news(ticker)
        except Exception as exc:
            logger.warning("Polygon news failed for %s: %s", ticker, exc)

    pos = sum(1 for i in items if i.sentiment == "positive")
    neg = sum(1 for i in items if i.sentiment == "negative")
    neu = sum(1 for i in items if i.sentiment == "neutral")

    return NewsSnapshot(
        ticker   = ticker,
        items    = items,
        score    = _score_items(items),
        positive = pos,
        neutral  = neu,
        negative = neg,
    )
