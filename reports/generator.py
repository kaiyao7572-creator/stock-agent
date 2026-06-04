"""
Daily report generator.

Builds a structured Markdown report from the top-N analyses stored
in the database.  Returned as a dict that both the API route and the
Discord integration can consume.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, desc

from database.database import get_session
from database.models   import Analysis, Stock

logger = logging.getLogger(__name__)


async def generate_daily_report(top_n: int = 10) -> dict[str, Any]:
    """
    Returns a dict:
    {
        "generated_at": ISO timestamp,
        "top_stocks":   [ {ticker, score, confidence, sector, ...}, ... ],
        "markdown":     "# Daily Report\n..."
    }
    """
    since = datetime.utcnow() - timedelta(hours=36)   # include last night's scan

    async with get_session() as db:
        # Latest analysis per ticker from the last 36 hours
        subq = (
            select(
                Analysis.ticker,
                Analysis.final_score,
                Analysis.confidence,
                Analysis.bull_case,
                Analysis.bear_case,
                Analysis.timestamp,
                Stock.sector,
                Stock.company_name,
            )
            .join(Stock, Stock.ticker == Analysis.ticker, isouter=True)
            .where(Analysis.timestamp >= since)
            .order_by(Analysis.ticker, desc(Analysis.timestamp))
            .distinct(Analysis.ticker)
        )
        rows = (await db.execute(subq)).all()

    # Sort by final_score desc
    sorted_rows = sorted(rows, key=lambda r: r.final_score or 0, reverse=True)[:top_n]

    top_stocks = []
    for row in sorted_rows:
        top_stocks.append({
            "ticker":       row.ticker,
            "final_score":  round(row.final_score or 0, 1),
            "confidence":   round(row.confidence   or 0, 1),
            "sector":       row.sector or "Unknown",
            "company_name": row.company_name or row.ticker,
            "bull_case":    (row.bull_case or "")[:200],
            "bear_case":    (row.bear_case or "")[:200],
            "analysed_at":  row.timestamp.isoformat() if row.timestamp else "",
        })

    markdown = _build_markdown(top_stocks)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "top_stocks":   top_stocks,
        "markdown":     markdown,
    }


def _build_markdown(stocks: list[dict]) -> str:
    lines = [
        f"# 📅 Daily Stock Research Report",
        f"*Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
        "---",
        "",
        f"## Top {len(stocks)} Stocks",
        "",
        "| # | Ticker | Company | Score | Confidence | Sector |",
        "|---|--------|---------|-------|------------|--------|",
    ]

    for i, s in enumerate(stocks, start=1):
        lines.append(
            f"| {i} | **{s['ticker']}** | {s['company_name']} "
            f"| {s['final_score']} | {s['confidence']}% | {s['sector']} |"
        )

    lines += ["", "---", ""]

    for s in stocks:
        lines += [
            f"### {s['ticker']} — {s['company_name']}",
            f"**Score:** {s['final_score']} &nbsp;|&nbsp; "
            f"**Confidence:** {s['confidence']}% &nbsp;|&nbsp; **Sector:** {s['sector']}",
            "",
            f"🐂 **Bull:** {s['bull_case'] or 'N/A'}",
            "",
            f"🐻 **Bear:** {s['bear_case'] or 'N/A'}",
            "",
            "---",
            "",
        ]

    lines.append("> ⚠️ This is AI-generated research, not financial advice.")
    return "\n".join(lines)
