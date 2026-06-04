# 📊 AI Stock Research Agent

A production-ready AI-powered stock research platform.  
**It never places trades.** It ranks stocks, explains reasoning, and tracks its own accuracy.

---

## Architecture

```
TradingView Alert
      │
      ▼
POST /webhook/tradingview
      │  (async queue)
      ▼
┌─────────────────────┐
│   Daily Scanner     │◄── APScheduler (23:00 UTC)
│  run_single_ticker  │
└──────┬──────────────┘
       │
       ├─► Market Data  (Finnhub → Polygon → Alpha Vantage)
       ├─► Technicals   (Finnhub candles / Polygon)
       ├─► News         (Finnhub / Polygon)
       │
       ▼
   Scoring Engine
  (weighted formula)
       │
       ▼
  Cerebras LLM
  (analysis text)
       │
       ├─► SQLite / PostgreSQL
       └─► Discord Webhook
```

---

## Quick Start

```bash
# 1. Clone and enter directory
git clone <your-repo>
cd stock-agent

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 5. Run
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

---

## API Reference

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/health` | Liveness check |
| POST | `/webhook/tradingview` | Receive TradingView alerts |
| GET | `/analysis/{ticker}` | Latest analysis for a ticker |
| POST | `/analysis/{ticker}/refresh` | Trigger on-demand re-analysis |
| GET | `/top-stocks?n=10` | Top N stocks by score |
| GET | `/report/daily` | Full daily report (JSON + Markdown) |
| GET | `/metrics` | Historical accuracy statistics |

Interactive docs available at `http://localhost:8000/docs`

---

## TradingView Setup

1. Create an alert in TradingView.
2. Set the **Webhook URL** to `https://your-domain.com/webhook/tradingview`
3. Set the **Message** body to:

```json
{
  "ticker":   "{{ticker}}",
  "close":    "{{close}}",
  "volume":   "{{volume}}",
  "interval": "{{interval}}"
}
```

---

## Scoring Formula

| Factor | Weight | Data Source |
|--------|--------|-------------|
| Revenue Growth | 25% | Fundamentals |
| Earnings Growth | 20% | EPS / P/E |
| Trend Strength | 20% | SMA / MACD |
| Volume Strength | 15% | Volume ratio |
| News Sentiment | 10% | Headlines |
| Financial Health | 10% | D/E, FCF |

`Final Score = Σ(component × weight)`, normalised 0–100.

---

## Confidence Levels

| Score | Meaning |
|-------|---------|
| 90–100 | Exceptional evidence |
| 80–89 | Strong evidence |
| 70–79 | Moderate evidence |
| 60–69 | Weak evidence |
| < 60 | Insufficient — avoid acting on it |

---

## Database

Default: `SQLite` via `aiosqlite`.  
Switch to PostgreSQL by changing `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

No code changes needed — SQLAlchemy handles both.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Deployment

### Railway / Render
Set all environment variables in the platform dashboard.  
Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

### VPS (systemd)
```ini
[Service]
WorkingDirectory=/opt/stock-agent
ExecStart=/opt/stock-agent/.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
EnvironmentFile=/opt/stock-agent/.env
Restart=always
```

---

## Safety

- This system **never** places trades or sends buy/sell orders.
- All outputs are labelled as research, not financial advice.
- Confidence scores are honest reflections of data quality.
- Every analysis includes both bull and bear cases.

---

## Roadmap

- [ ] Portfolio tracking
- [ ] Earnings calendar integration
- [ ] SEC filing analysis
- [ ] Insider trading detection
- [ ] Multi-agent analysis
- [ ] Backtesting engine
- [ ] Custom web dashboard
- [ ] Mobile app
