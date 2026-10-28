"""Cost ledger: every Meta Model API call is recorded with its cost, and a
configurable daily cap (UTC day) blocks calls that would exceed it. A job,
such as one agent run, can log its calls under a tag and have its own cap."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime

from vigia.timeutil import to_iso, utcnow


class BudgetExceeded(RuntimeError):
    """Raised before a call that would push today's spend over the daily cap."""


class CostLedger:
    def __init__(
        self,
        conn: sqlite3.Connection,
        daily_budget_usd: float,
        now: Callable[[], datetime] = utcnow,
    ):
        self._conn = conn
        self.daily_budget_usd = daily_budget_usd
        self._now = now

    def record(
        self,
        *,
        model: str,
        purpose: str,
        cost_usd: float,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO api_calls (called_at, model, purpose, input_tokens, output_tokens,
                                      cost_usd, latency_ms, ok, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (to_iso(self._now()), model, purpose, input_tokens, output_tokens,
             cost_usd, latency_ms, int(error is None), error),
        )
        self._conn.commit()

    def spent_today(self) -> float:
        day = to_iso(self._now())[:10]
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM api_calls WHERE substr(called_at, 1, 10) = ?",
            (day,),
        ).fetchone()
        return row["total"]

    def ensure_budget(self, estimated_cost_usd: float) -> None:
        spent = self.spent_today()
        if spent + estimated_cost_usd > self.daily_budget_usd:
            raise BudgetExceeded(
                f"daily budget ${self.daily_budget_usd:.2f} would be exceeded: "
                f"spent ${spent:.4f} today, next call estimated at ${estimated_cost_usd:.4f}"
            )

    def spent_on(self, tag: str) -> float:
        """The cost of every call logged under a tag, i.e. whose purpose starts with '<tag>/'."""
        prefix = f"{tag}/"
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM api_calls WHERE substr(purpose, 1, ?) = ?",
            (len(prefix), prefix),
        ).fetchone()
        return row["total"]

    def ensure_tag_budget(self, tag: str, budget_usd: float, estimated_cost_usd: float) -> None:
        spent = self.spent_on(tag)
        if spent + estimated_cost_usd > budget_usd:
            raise BudgetExceeded(
                f"budget ${budget_usd:.2f} of {tag} would be exceeded: "
                f"spent ${spent:.4f}, next call estimated at ${estimated_cost_usd:.4f}"
            )
