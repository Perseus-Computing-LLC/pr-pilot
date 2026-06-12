"""Tests for dashboard authentication (issue #8)."""

from fastapi.testclient import TestClient

import src.main as main

client = TestClient(main.app)


def test_dashboard_disabled_returns_404_when_no_token(monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TOKEN", "")
    assert client.get("/dashboard/reviews").status_code == 404


def test_dashboard_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TOKEN", "s3cret")
    # No header -> 401
    assert client.get("/dashboard/reviews").status_code == 401
    # Wrong token -> 401
    resp = client.get(
        "/dashboard/reviews", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401


def test_dashboard_allows_correct_token(monkeypatch):
    monkeypatch.setattr(main, "DASHBOARD_TOKEN", "s3cret")
    resp = client.get(
        "/dashboard/reviews", headers={"Authorization": "Bearer s3cret"}
    )
    assert resp.status_code == 200
    assert "reviews" in resp.json()


def test_health_remains_public():
    assert client.get("/health").status_code == 200
