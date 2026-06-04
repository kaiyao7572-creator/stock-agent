"""
Unit tests for the scoring engine.
Run with: pytest tests/ -v
"""

import pytest
from data.market     import MarketSnapshot
from data.technicals import TechnicalSnapshot
from data.news       import NewsSnapshot, NewsItem
from scoring.ranking  import calculate_scores, _clamp


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_market(**kwargs) -> MarketSnapshot:
    defaults = dict(
        ticker="TEST",
        current_price=150.0,
        week_52_high=200.0,
        week_52_low=100.0,
        market_cap=1e12,
        volume=5e6,
        avg_volume=4e6,
        pe_ratio=20.0,
        eps=7.5,
        revenue_growth=0.15,
        profit_growth=0.12,
        debt_to_equity=0.5,
        free_cash_flow=5e9,
        institutional_ownership=70.0,
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


def make_tech(**kwargs) -> TechnicalSnapshot:
    defaults = dict(
        ticker="TEST",
        sma_20=145.0,
        sma_50=140.0,
        sma_200=130.0,
        rsi=55.0,
        macd=1.5,
        macd_signal=1.0,
        macd_hist=0.5,
        volume_ratio=1.3,
        trend_direction="bullish",
        trend_strength=75.0,
    )
    defaults.update(kwargs)
    return TechnicalSnapshot(**defaults)


def make_news(score=65.0, pos=5, neu=3, neg=2) -> NewsSnapshot:
    items = (
        [NewsItem("good news", "test", "", "", "positive")] * pos +
        [NewsItem("meh",       "test", "", "", "neutral")]  * neu +
        [NewsItem("bad news",  "test", "", "", "negative")] * neg
    )
    return NewsSnapshot(ticker="TEST", items=items, score=score,
                        positive=pos, neutral=neu, negative=neg)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_clamp():
    assert _clamp(150)   == 100
    assert _clamp(-10)   == 0
    assert _clamp(50)    == 50


def test_scores_are_in_range():
    bundle = calculate_scores(make_market(), make_tech(), make_news())
    for attr in ("revenue_score", "earnings_score", "trend_score",
                 "volume_score", "news_score", "health_score",
                 "final_score", "confidence"):
        val = getattr(bundle, attr)
        assert 0 <= val <= 100, f"{attr} = {val} out of range"


def test_high_growth_raises_revenue_score():
    high = make_market(revenue_growth=0.30)
    low  = make_market(revenue_growth=-0.05)
    tech = make_tech()
    news = make_news()
    assert calculate_scores(high, tech, news).revenue_score > \
           calculate_scores(low,  tech, news).revenue_score


def test_bearish_trend_lowers_trend_score():
    bull = make_tech(trend_direction="bullish", trend_strength=80)
    bear = make_tech(trend_direction="bearish", trend_strength=80, rsi=35)
    m    = make_market()
    n    = make_news()
    assert calculate_scores(m, bull, n).trend_score > \
           calculate_scores(m, bear, n).trend_score


def test_negative_news_lowers_score():
    good_news = make_news(score=80, pos=8, neu=1, neg=1)
    bad_news  = make_news(score=20, pos=1, neu=1, neg=8)
    m = make_market()
    t = make_tech()
    assert calculate_scores(m, t, good_news).news_score > \
           calculate_scores(m, t, bad_news).news_score


def test_high_debt_lowers_health_score():
    safe  = make_market(debt_to_equity=0.2, free_cash_flow=1e9)
    risky = make_market(debt_to_equity=4.0, free_cash_flow=-5e8)
    t = make_tech()
    n = make_news()
    assert calculate_scores(safe,  t, n).health_score > \
           calculate_scores(risky, t, n).health_score


def test_final_score_is_weighted_sum():
    bundle = calculate_scores(make_market(), make_tech(), make_news())
    expected = (
        bundle.revenue_score  * 0.25 +
        bundle.earnings_score * 0.20 +
        bundle.trend_score    * 0.20 +
        bundle.volume_score   * 0.15 +
        bundle.news_score     * 0.10 +
        bundle.health_score   * 0.10
    )
    assert abs(bundle.final_score - expected) < 0.01
