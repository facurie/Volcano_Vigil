from datetime import timedelta

import pytest

from conftest import NOW
from vigia.meta.ledger import BudgetExceeded, CostLedger


@pytest.fixture
def ledger(conn):
    return CostLedger(conn, daily_budget_usd=1.00, now=lambda: NOW)


def test_record_stores_the_call_with_its_cost(ledger, conn):
    ledger.record(model="muse-spark", purpose="smoke:assess", cost_usd=0.012,
                  input_tokens=1500, output_tokens=400, latency_ms=2300)

    row = conn.execute("SELECT * FROM api_calls").fetchone()
    assert (row["model"], row["purpose"], row["cost_usd"]) == ("muse-spark", "smoke:assess", 0.012)
    assert (row["input_tokens"], row["output_tokens"], row["latency_ms"]) == (1500, 400, 2300)
    assert row["called_at"] == "2026-10-26T18:30:05Z"
    assert row["ok"] == 1


def test_failed_calls_are_recorded_with_their_error(ledger, conn):
    ledger.record(model="sam", purpose="segment", cost_usd=0.0, error="HTTP 429")

    row = conn.execute("SELECT ok, error FROM api_calls").fetchone()
    assert (row["ok"], row["error"]) == (0, "HTTP 429")


def test_spent_today_only_counts_the_current_utc_day(conn):
    yesterday = CostLedger(conn, daily_budget_usd=1.0, now=lambda: NOW - timedelta(days=1))
    today = CostLedger(conn, daily_budget_usd=1.0, now=lambda: NOW)
    yesterday.record(model="m", purpose="p", cost_usd=0.50)
    today.record(model="m", purpose="p", cost_usd=0.25)
    today.record(model="m", purpose="p", cost_usd=0.10)

    assert today.spent_today() == pytest.approx(0.35)


def test_ensure_budget_allows_a_call_that_fits(ledger):
    ledger.record(model="m", purpose="p", cost_usd=0.60)

    ledger.ensure_budget(estimated_cost_usd=0.40)


def test_ensure_budget_blocks_a_call_that_would_exceed_the_cap(ledger):
    ledger.record(model="m", purpose="p", cost_usd=0.60)

    with pytest.raises(BudgetExceeded, match="1.00"):
        ledger.ensure_budget(estimated_cost_usd=0.41)
