"""
Scoring engine.

Weights (must sum to 1.0):
  Revenue Growth  25%
  Earnings Growth 20%
  Trend Strength  20%
  Volume Strength 15%
  News Sentiment  10%
  Financial Health10%

Each sub-score is independently normalised to 0–100 before weighting.
"""

from dataclasses import dataclass

from data.market     import MarketSnapshot
from data.technicals import TechnicalSnapshot
from data.news       import NewsSnapshot


WEIGHTS = {
    "revenue":  0.25,
    "earnings": 0.20,
    "trend":    0.20,
    "volume":   0.15,
    "news":     0.10,
    "health":   0.10,
}


@dataclass
class ScoreBundle:
    revenue_score:  float
    earnings_score: float
    trend_score:    float
    volume_score:   float
    news_score:     float
    health_score:   float
    final_score:    float
    confidence:     float

    def as_dict(self) -> dict:
        return {
            "revenue_score":  self.revenue_score,
            "earnings_score": self.earnings_score,
            "trend_score":    self.trend_score,
            "volume_score":   self.volume_score,
            "news_score":     self.news_score,
            "health_score":   self.health_score,
            "final_score":    self.final_score,
            "confidence":     self.confidence,
        }


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _revenue_score(snap: MarketSnapshot) -> float:
    """Scale revenue growth % → 0–100.  >30% → 100, <-10% → 0."""
    g = snap.revenue_growth  # e.g. 0.12 = 12%
    if g is None:
        return 50.0
    # Already a ratio or percentage?  Normalise to ratio.
    if abs(g) > 5:        # likely came in as percentage points
        g /= 100
    return _clamp((g + 0.10) / 0.40 * 100)


def _earnings_score(snap: MarketSnapshot) -> float:
    """EPS positive and P/E in reasonable range → higher score."""
    score = 50.0
    if snap.eps > 0:
        score += 20
    if 0 < snap.pe_ratio < 30:
        score += 15
    elif 30 <= snap.pe_ratio < 50:
        score += 5
    elif snap.pe_ratio < 0:
        score -= 20
    g = snap.profit_growth
    if g is not None:
        if abs(g) > 5:
            g /= 100
        score += _clamp(g * 100, -30, 30)
    return _clamp(score)


def _trend_score(tech: TechnicalSnapshot) -> float:
    """Trend direction + strength + RSI."""
    base = tech.trend_strength  # 0–100

    # RSI bonus/penalty
    rsi = tech.rsi or 50
    if 40 < rsi < 60:
        base += 5   # neutral RSI is fine
    elif rsi >= 70:
        base -= 10  # overbought
    elif rsi <= 30:
        base += 10  # oversold (potential reversal opportunity)

    # MACD histogram bonus
    if tech.macd_hist is not None:
        if tech.macd_hist > 0:
            base += 5
        else:
            base -= 5

    return _clamp(base)


def _volume_score(snap: MarketSnapshot, tech: TechnicalSnapshot) -> float:
    """Volume vs average; higher ratio → stronger conviction."""
    ratio = tech.volume_ratio or 1.0
    # 1.0 = average, 2.0 = double → 75/100, 0.5 = half → 25/100
    return _clamp((ratio - 0.5) / 1.5 * 100)


def _news_score(news: NewsSnapshot) -> float:
    return _clamp(news.score)


def _health_score(snap: MarketSnapshot) -> float:
    """Debt/equity + free cash flow proxy."""
    score = 60.0
    de = snap.debt_to_equity
    if de == 0:
        score += 10   # no debt
    elif de < 0.5:
        score += 5
    elif 0.5 <= de < 1.5:
        pass          # neutral
    elif 1.5 <= de < 3.0:
        score -= 15
    else:
        score -= 30

    if snap.free_cash_flow > 0:
        score += 10
    elif snap.free_cash_flow < 0:
        score -= 10

    if snap.institutional_ownership > 50:
        score += 10  # smart money present

    return _clamp(score)


def _confidence(scores: dict, snap: MarketSnapshot) -> float:
    """
    Confidence reflects DATA QUALITY and signal agreement, not just score level.
    Penalised when key data points are missing or signals conflict.
    """
    conf = 70.0

    # Reward when data is complete
    if snap.revenue_growth not in (None, 0):
        conf += 5
    if snap.eps not in (None, 0):
        conf += 5
    if snap.market_cap > 0:
        conf += 5

    # Penalise extreme divergence between sub-scores
    vals  = list(scores.values())
    spread = max(vals) - min(vals)
    conf -= spread * 0.10  # wide spread = conflicting signals

    return _clamp(conf)


def calculate_scores(
    market: MarketSnapshot,
    tech:   TechnicalSnapshot,
    news:   NewsSnapshot,
) -> ScoreBundle:
    rev  = _revenue_score(market)
    earn = _earnings_score(market)
    trnd = _trend_score(tech)
    vol  = _volume_score(market, tech)
    nws  = _news_score(news)
    hlth = _health_score(market)

    final = (
        rev  * WEIGHTS["revenue"]  +
        earn * WEIGHTS["earnings"] +
        trnd * WEIGHTS["trend"]    +
        vol  * WEIGHTS["volume"]   +
        nws  * WEIGHTS["news"]     +
        hlth * WEIGHTS["health"]
    )

    component_scores = {
        "revenue": rev, "earnings": earn, "trend": trnd,
        "volume": vol,  "news": nws,      "health": hlth,
    }
    conf = _confidence(component_scores, market)

    return ScoreBundle(
        revenue_score  = rev,
        earnings_score = earn,
        trend_score    = trnd,
        volume_score   = vol,
        news_score     = nws,
        health_score   = hlth,
        final_score    = _clamp(final),
        confidence     = conf,
    )
