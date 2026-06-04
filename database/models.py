"""
ORM models. Designed to be PostgreSQL-compatible from day one;
SQLite is just the default engine.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text,
    DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    id           = Column(Integer, primary_key=True, index=True)
    ticker       = Column(String(10), unique=True, nullable=False, index=True)
    company_name = Column(String(255))
    sector       = Column(String(100))
    industry     = Column(String(100))
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Analysis(Base):
    __tablename__ = "analyses"

    id               = Column(Integer, primary_key=True, index=True)
    ticker           = Column(String(10), nullable=False, index=True)
    timestamp        = Column(DateTime, default=datetime.utcnow, index=True)

    # Component scores (0–100 each)
    revenue_score    = Column(Float)
    earnings_score   = Column(Float)
    trend_score      = Column(Float)
    volume_score     = Column(Float)
    news_score       = Column(Float)
    health_score     = Column(Float)

    # Composite
    final_score      = Column(Float, index=True)
    confidence       = Column(Float)

    # AI narrative
    bull_case        = Column(Text)
    bear_case        = Column(Text)
    analysis_text    = Column(Text)

    __table_args__ = (
        Index("ix_analyses_ticker_ts", "ticker", "timestamp"),
    )


class PerformanceTracking(Base):
    __tablename__ = "performance_tracking"

    id               = Column(Integer, primary_key=True, index=True)
    ticker           = Column(String(10), nullable=False, index=True)
    analysis_date    = Column(DateTime, default=datetime.utcnow)
    analysis_id      = Column(Integer, ForeignKey("analyses.id"), nullable=True)

    starting_price   = Column(Float)
    price_7d         = Column(Float, nullable=True)
    price_30d        = Column(Float, nullable=True)
    price_90d        = Column(Float, nullable=True)

    # Derived accuracy fields (populated retroactively by the scheduler)
    return_7d        = Column(Float, nullable=True)
    return_30d       = Column(Float, nullable=True)
    return_90d       = Column(Float, nullable=True)
    prediction_score = Column(Float, nullable=True)   # 0–100 accuracy rating
