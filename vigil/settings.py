"""Runtime settings read from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_USER_AGENT = "VolcanoVigil/0.1 (volcano webcam monitor; hackathon project)"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    sources_path: Path
    prompts_path: Path
    calibration_path: Path
    user_agent: str
    daily_budget_usd: float
    alerts_path: Path = Path("config/alerts.yaml")
    alert_reserve_usd: float = 0.75   # of the daily cap, kept for the fountaining alerts (vigil.alerts)
    telegram_token: str | None = None  # the alert bot's token: a secret, never printed
    telegram_chat: str | None = None   # the public channel: @name or its numeric id

    @property
    def pipeline_budget_usd(self) -> float:
        """What the pipeline may spend in a UTC day: the cap less the alerts' reserve."""
        return max(0.0, self.daily_budget_usd - self.alert_reserve_usd)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        return cls(
            data_dir=data_dir,
            db_path=Path(os.getenv("DB_PATH", str(data_dir / "vigil.sqlite"))),
            sources_path=Path(os.getenv("SOURCES_PATH", "config/sources.yaml")),
            prompts_path=Path(os.getenv("PROMPTS_PATH", "config/prompts.yaml")),
            calibration_path=Path(os.getenv("CALIBRATION_PATH", "config/calibration.yaml")),
            user_agent=os.getenv("HTTP_USER_AGENT", DEFAULT_USER_AGENT),
            daily_budget_usd=float(os.getenv("DAILY_BUDGET_USD", "5.00")),
            alerts_path=Path(os.getenv("ALERTS_PATH", "config/alerts.yaml")),
            alert_reserve_usd=float(os.getenv("ALERT_RESERVE_USD", "0.75")),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat=os.getenv("TELEGRAM_CHAT_ID") or None,
        )
