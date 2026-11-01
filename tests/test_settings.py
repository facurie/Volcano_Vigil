from pathlib import Path

import pytest

from vigil.settings import Settings


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Never read the developer's .env: it holds real keys, and a failing assertion would print them."""
    monkeypatch.setattr("vigil.settings.load_dotenv", lambda: None)
    for name in ("ALERTS_PATH", "ALERT_RESERVE_USD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DAILY_BUDGET_USD"):
        monkeypatch.delenv(name, raising=False)


def test_alerts_and_telegram_settings_have_defaults_and_no_token():
    settings = Settings.from_env()

    assert settings.alerts_path == Path("config/alerts.yaml")
    assert settings.alert_reserve_usd == 0.75
    assert settings.telegram_token is None and settings.telegram_chat is None
    assert settings.pipeline_budget_usd == 5.0 - 0.75


def test_alerts_and_telegram_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ALERT_RESERVE_USD", "0.5")
    monkeypatch.setenv("DAILY_BUDGET_USD", "4")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@volcano_vigil")

    settings = Settings.from_env()

    assert (settings.alert_reserve_usd, settings.pipeline_budget_usd) == (0.5, 3.5)
    assert (settings.telegram_token, settings.telegram_chat) == ("123:abc", "@volcano_vigil")


def test_the_pipeline_never_gets_a_negative_budget(monkeypatch):
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.5")

    assert Settings.from_env().pipeline_budget_usd == 0.0
