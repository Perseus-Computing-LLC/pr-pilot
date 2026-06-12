"""Tests for Stripe price-id validation (issue #13)."""

import pytest

import src.stripe_handler as sh


def test_no_default_price_ids():
    """Price IDs must not ship with placeholder defaults."""
    for plan, value in sh.PRICE_IDS.items():
        assert not value.startswith("TEMP_"), f"{plan} has a placeholder default"


def test_invalid_price_id_rejected(monkeypatch):
    """A non 'price_' id is rejected before any Stripe call."""
    monkeypatch.setattr(sh, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setitem(sh.PRICE_IDS, "team", "TEMP_bogus")
    with pytest.raises(ValueError):
        sh.create_checkout_session("team")


def test_missing_price_id_rejected(monkeypatch):
    monkeypatch.setattr(sh, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setitem(sh.PRICE_IDS, "team", "")
    with pytest.raises(ValueError):
        sh.create_checkout_session("team")
