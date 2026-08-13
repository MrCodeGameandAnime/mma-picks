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
    odds_api_sport_key: str = "mma_mixed_martial_arts"
    odds_api_regions: str = "us"
    odds_api_markets: str = "h2h"
    odds_api_timeout_seconds: float = 10.0
    flask_secret_key: str = "dev-only-change-me"
    server_host: str = "127.0.0.1"
    server_port: int = 5000


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
        odds_api_sport_key=values.get("ODDS_API_SPORT_KEY", "mma_mixed_martial_arts"),
        odds_api_regions=values.get("ODDS_API_REGIONS", "us"),
        odds_api_markets=values.get("ODDS_API_MARKETS", "h2h"),
        odds_api_timeout_seconds=float(values.get("ODDS_API_TIMEOUT_SECONDS", "10")),
        flask_secret_key=values.get("FLASK_SECRET_KEY", "dev-only-change-me"),
        server_host=values.get("FLASK_HOST", "127.0.0.1"),
        server_port=int(values.get("PORT", "5000")),
    )
