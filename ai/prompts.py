"""
All prompt templates in one place.
Keeping them separate from the client makes iterating easy without
touching infrastructure code.
"""

SYSTEM_PROMPT = """You are a professional equity research analyst at a top-tier investment bank.

Rules:
- You NEVER guarantee future performance or promise profits.
- You analyze evidence only and state confidence levels honestly.
- You ALWAYS include risks alongside opportunities.
- You treat your outputs as research, not financial advice.
- Use markdown formatting with clear section headers.
- Be specific: cite data points from the provided metrics.
- Confidence scores must reflect data quality, not wishful thinking.
"""

ANALYSIS_USER_PROMPT = """Analyze the following stock and provide a structured research report.

## Ticker: {ticker}

## Market Data
{market_data}

## Technical Indicators
{technical_data}

## News Sentiment
{news_data}

## Component Scores (0–100)
- Revenue Growth Score : {revenue_score:.1f}
- Earnings Score       : {earnings_score:.1f}
- Trend Score          : {trend_score:.1f}
- Volume Score         : {volume_score:.1f}
- News Sentiment Score : {news_score:.1f}
- Financial Health Score: {health_score:.1f}
- **Final Score**      : {final_score:.1f}

---

Please return EXACTLY these sections in order:

### 1. Business Summary
Brief overview of what the company does and its position in its industry.

### 2. Growth Catalysts
3–5 specific catalysts identified from the data above.

### 3. Risks
3–5 specific risks the data reveals or implies.

### 4. Technical Analysis
Interpret the SMA alignment, RSI, MACD, and volume ratio.

### 5. Bull Case
Best plausible outcome with supporting evidence from the data.

### 6. Bear Case
Worst plausible outcome with supporting evidence from the data.

### 7. Confidence Score
A single integer 0–100.  
Interpret as:
- 90–100: Exceptional evidence
- 80–89: Strong evidence
- 70–79: Moderate evidence
- 60–69: Weak evidence
- <60: Insufficient evidence — avoid

### 8. Overall Rating
One of: STRONG BUY / BUY / HOLD / SELL / STRONG SELL  
Followed by a single sentence justification.
"""


def build_analysis_prompt(
    ticker: str,
    market_data: dict,
    technical_data: dict,
    news_data: dict,
    scores: dict,
) -> tuple[str, str]:
    """
    Returns (system_prompt, user_prompt) ready to pass to cerebras_client.complete().
    """
    def fmt_dict(d: dict) -> str:
        lines = []
        for k, v in d.items():
            if isinstance(v, float):
                lines.append(f"- {k}: {v:,.2f}")
            else:
                lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    user = ANALYSIS_USER_PROMPT.format(
        ticker          = ticker,
        market_data     = fmt_dict(market_data),
        technical_data  = fmt_dict(technical_data),
        news_data       = fmt_dict(news_data),
        **scores,
    )
    return SYSTEM_PROMPT, user
