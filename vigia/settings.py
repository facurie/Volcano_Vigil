"""Runtime settings read from the environment (and a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_USER_AGENT = "VigiaAndino/0.1 (volcano webcam monitor; hackathon project)"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    sources_path: Path
    user_agent: str

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        return cls(
            data_dir=data_dir,
            db_path=Path(os.getenv("DB_PATH", str(data_dir / "vigia.sqlite"))),
            sources_path=Path(os.getenv("SOURCES_PATH", "config/sources.yaml")),
            user_agent=os.getenv("HTTP_USER_AGENT", DEFAULT_USER_AGENT),
        )
