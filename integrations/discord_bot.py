"""
Discord webhook integration.

Sends rich embeds for individual stock analyses and daily reports.
Uses raw HTTP rather than discord.py's webhook client to avoid
the full bot overhead for simple one-way notifications.
"""

import logging
from datetime import datetime

import httpx

from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()


def _score_color(score: float) -> int:
    """Map 0–100 score to a Discord embed colour (RGB integer)."""
    if score >= 80:
        return 0x2ECC71   # green
    if score >= 60:
        return 0xF39C12   # amber
    return 0xE74C3C       # red


def _confidence_label(confidence: float) -> str:
    if confidence >= 90:
        return "🟢 Exceptional"
    if confidence >= 80:
        return "🟢 Strong"
    if confidence >= 70:
        return "🟡 Moderate"
    if confidence >= 60:
        return "🟠 Weak"
    return "🔴 Insufficient"


async def send_analysis_alert(
    ticker: str,
    final_score: float,
    confidence: float,
    bull_case: str,
    bear_case: str,
    dashboard_url: str = "",
) -> bool:
    """
    Send a single-stock analysis embed to Discord.
    Returns True on success, False on failure (never raises).
    """
    if not settings.discord_webhook:
        logger.warning("DISCORD_WEBHOOK not configured — skipping notification.")
        return False

    # Truncate cases to fit embed limits
    bull = bull_case[:300] + "…" if len(bull_case) > 300 else bull_case
    bear = bear_case[:300] + "…" if len(bear_case) > 300 else bear_case

    embed = {
        "title":       f"📊 Stock Analysis: {ticker}",
        "color":       _score_color(final_score),
        "timestamp":   datetime.utcnow().isoformat(),
        "fields": [
            {"name": "Final Score",  "value": f"**{final_score:.1f} / 100**", "inline": True},
            {"name": "Confidence",   "value": _confidence_label(confidence),  "inline": True},
            {"name": "🐂 Bull Case", "value": bull or "N/A",                  "inline": False},
            {"name": "🐻 Bear Case", "value": bear or "N/A",                  "inline": False},
        ],
        "footer": {"text": "AI Stock Research Agent • Not financial advice"},
    }

    if dashboard_url:
        embed["url"] = dashboard_url

    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(settings.discord_webhook, json=payload)
        r.raise_for_status()
        logger.info("Discord alert sent for %s", ticker)
        return True
    except Exception as exc:
        logger.error("Discord send failed: %s", exc)
        return False


async def send_daily_report(top_stocks: list[dict]) -> bool:
    """
    Send a daily summary embed with the top N stocks.
    Each item in top_stocks: {ticker, final_score, confidence, sector}.
    """
    if not settings.discord_webhook:
        return False

    lines = []
    for i, stock in enumerate(top_stocks[:10], start=1):
        ticker  = stock.get("ticker", "?")
        score   = stock.get("final_score", 0)
        conf    = stock.get("confidence", 0)
        sector  = stock.get("sector", "Unknown")
        lines.append(f"{i}. **{ticker}** — Score: {score:.1f} | Conf: {conf:.0f}% | {sector}")

    description = "\n".join(lines) or "No stocks analysed today."

    embed = {
        "title":       "📅 Daily Top Stocks Report",
        "description": description,
        "color":       0x3498DB,
        "timestamp":   datetime.utcnow().isoformat(),
        "footer":      {"text": "AI Stock Research Agent • Not financial advice"},
    }

    payload = {"embeds": [embed]}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(settings.discord_webhook, json=payload)
        r.raise_for_status()
        logger.info("Daily report sent to Discord (%d stocks)", len(top_stocks))
        return True
    except Exception as exc:
        logger.error("Discord daily report failed: %s", exc)
        return False
