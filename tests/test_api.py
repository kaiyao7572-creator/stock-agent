import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:8000")

from fastapi.testclient import TestClient

import app


client = TestClient(app.app)


def test_health_route():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ticker_validation_rejects_invalid_ticker():
    response = client.get("/analysis/BAD!")
    assert response.status_code == 422


def test_protected_refresh_rejects_missing_api_key():
    response = client.post("/analysis/AAPL/refresh")
    assert response.status_code == 401


def test_protected_refresh_accepts_valid_api_key(monkeypatch):
    async def fake_run_single_ticker(ticker):
        return {"ticker": ticker}

    monkeypatch.setattr(app, "run_single_ticker", fake_run_single_ticker)
    response = client.post(
        "/analysis/AAPL/refresh",
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "started", "ticker": "AAPL"}
