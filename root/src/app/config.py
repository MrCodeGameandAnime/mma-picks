from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = ROOT_DIR / "data" / "tracker.db"


@dataclass(frozen=True)
class AppConfig:
    database_path: Path = DEFAULT_DATABASE_PATH
    odds_api_key: str | None = None
    flask_secret_key: str = "dev-only-change-me"


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    load_environment_file: bool = True,
) -> AppConfig:
    if load_environment_file:
        load_dotenv(ROOT_DIR / ".env", override=False)

    values = environ if environ is not None else os.environ
    database_path = Path(values.get("DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))
    return AppConfig(
        database_path=database_path,
        odds_api_key=values.get("ODDS_API_KEY"),
        flask_secret_key=values.get("FLASK_SECRET_KEY", "dev-only-change-me"),
    )
