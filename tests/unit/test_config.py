"""Config defaults and the production secret gate (T003).

`Config` is imported inside each test rather than at module scope on purpose: the
env-override test reloads `app.config`, which rebinds the class object. A module-level
import would go stale and later tests would monkeypatch a class that `validate()` no
longer resolves to.
"""
import importlib

import pytest


def _config():
    import app.config
    return app.config.Config


def test_payment_defaults_match_the_agreed_price():
    # The price the spec settled on: 2 keys → 5 credits, 1 credit = 1 hour,
    # +30 min per credit to extend, 15-minute overrun grace.
    cfg = _config()
    assert cfg.PAYMENT_ITEM_NAME == "Mann Co. Supply Crate Key"
    assert cfg.PAYMENT_ITEM_APPID == 440
    assert cfg.PAYMENT_MIN_KEYS == 2
    assert cfg.CREDITS_PER_KEY == 2.5
    assert int(cfg.PAYMENT_MIN_KEYS * cfg.CREDITS_PER_KEY) == 5
    assert cfg.CREDIT_MINUTES == 60
    assert cfg.EXTENSION_MINUTES == 30
    assert cfg.GRACE_MINUTES == 15


def test_poll_interval_stays_well_inside_steams_daily_budget():
    # Steam allows 100,000 calls/day per key. Guard against someone "tuning" this
    # to a value that would blow the budget and get the key rate-limited.
    assert 86_400 / _config().PAYMENT_POLL_SECONDS < 10_000


def test_payment_settings_are_env_overridable(monkeypatch):
    # FR-051: the price must move with the market without a code change.
    monkeypatch.setenv("CREDITS_PER_KEY", "3")
    monkeypatch.setenv("PAYMENT_MIN_KEYS", "1")
    import app.config
    importlib.reload(app.config)
    try:
        assert app.config.Config.CREDITS_PER_KEY == 3.0
        assert app.config.Config.PAYMENT_MIN_KEYS == 1
    finally:
        monkeypatch.undo()
        importlib.reload(app.config)


def test_production_without_payment_credentials_fails_fast(monkeypatch):
    """A missing Steam key used to just degrade personas. Now the poller would see
    no trades at all and every payment would hang unpaid with nothing looking
    broken — so it has to fail at startup instead."""
    cfg = _config()
    monkeypatch.setattr(cfg, "ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "real-secret")
    monkeypatch.delenv("STEAM_API_KEY", raising=False)
    monkeypatch.delenv("OPERATOR_TRADE_URL", raising=False)

    with pytest.raises(RuntimeError) as err:
        cfg.validate()
    assert "STEAM_API_KEY" in str(err.value)
    assert "OPERATOR_TRADE_URL" in str(err.value)


def test_production_with_all_credentials_passes(monkeypatch):
    cfg = _config()
    monkeypatch.setattr(cfg, "ENV", "production")
    monkeypatch.setenv("APP_SECRET_KEY", "real-secret")
    monkeypatch.setenv("STEAM_API_KEY", "real-key")
    monkeypatch.setenv(
        "OPERATOR_TRADE_URL",
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=x",
    )

    cfg.validate()  # must not raise


def test_development_does_not_require_payment_credentials(monkeypatch):
    cfg = _config()
    monkeypatch.setattr(cfg, "ENV", "development")
    monkeypatch.delenv("STEAM_API_KEY", raising=False)

    cfg.validate()  # dev stays runnable with no secrets at all
