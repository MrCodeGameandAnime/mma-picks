from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.app.db import DEFAULT_DATABASE_PATH
from src.app.providers.ufcstats_csv import UFCStatsSourceError
from src.app.services.ufc_catalog_import import ImportSummary, sync_catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import UFCStats CSV artifacts into MMAPicks.")
    parser.add_argument("--source", required=True, type=Path, help="UFCStats CSV directory")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    return parser


def _print_summary(summary: ImportSummary) -> None:
    for key, value in summary.as_dict().items():
        if isinstance(value, list):
            print(f"{key}: {', '.join(value) if value else '-'}")
        else:
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = sync_catalog(args.database, args.source)
    except (OSError, UFCStatsSourceError, ValueError) as exc:
        print(f"sync failed: {exc}", file=sys.stderr)
        return 2
    _print_summary(summary)
    return 1 if summary.has_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
