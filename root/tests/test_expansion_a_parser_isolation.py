import shutil
import subprocess
import sys
from pathlib import Path

from src.app.db import connect
from src.app.services.ufc_catalog_import import sync_catalog

from test_ufc_catalog_web import FIXTURE_DIR


def _copy_source(tmp_path: Path) -> Path:
    source_dir = tmp_path / "source"
    shutil.copytree(FIXTURE_DIR, source_dir)
    return source_dir


def _assert_only_second_event(database_path: Path, summary) -> None:
    assert summary.events_processed == 2
    assert summary.events_failed == 1
    assert summary.events_inserted == 1
    assert summary.has_failures
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE name = 'UFC Fixture One'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE name = 'UFC Fixture Two'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id IN (SELECT id FROM events WHERE name = 'UFC Fixture One')"
        ).fetchone()[0] == 0


def test_directory_sync_isolates_malformed_fight_detail_url(tmp_path):
    source_dir = _copy_source(tmp_path)
    details = source_dir / "ufc_fight_details.csv"
    details.write_text(
        details.read_text(encoding="utf-8").replace(
            "http://ufcstats.com/fight-details/aaaaaaaa11111111",
            "not-a-ufcstats-url",
            1,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tracker.db"
    summary = sync_catalog(database_path, source_dir)
    _assert_only_second_event(database_path, summary)
    assert any("fight detail line" in error for error in summary.errors)


def test_directory_sync_isolates_malformed_required_outcome(tmp_path):
    source_dir = _copy_source(tmp_path)
    results = source_dir / "ufc_fight_results.csv"
    results.write_text(
        results.read_text(encoding="utf-8").replace(
            "UFC Fixture One,Alpha One vs. Bravo Two,W/L,",
            "UFC Fixture One,Alpha One vs. Bravo Two,,",
            1,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tracker.db"
    summary = sync_catalog(database_path, source_dir)
    _assert_only_second_event(database_path, summary)
    assert any("missing OUTCOME" in error for error in summary.errors)


def test_directory_sync_isolates_malformed_fighter_content(tmp_path):
    source_dir = _copy_source(tmp_path)
    tott = source_dir / "ufc_fighter_tott.csv"
    tott.write_text(
        tott.read_text(encoding="utf-8").replace(
            "Bravo Two,--,155 lbs.,--,Southpaw,--,",
            "Bravo Two,--,155 lbs.,--,Southpaw,not-a-date,",
            1,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tracker.db"
    summary = sync_catalog(database_path, source_dir)
    _assert_only_second_event(database_path, summary)
    assert any("fighter" in error.lower() for error in summary.errors)


def test_cli_returns_one_for_malformed_directory_and_keeps_valid_event(tmp_path):
    source_dir = _copy_source(tmp_path)
    details = source_dir / "ufc_fight_details.csv"
    details.write_text(
        details.read_text(encoding="utf-8").replace(
            "http://ufcstats.com/fight-details/aaaaaaaa11111111",
            "not-a-ufcstats-url",
            1,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tracker.db"
    project_root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "tools" / "sync_ufc_stats.py"),
            "--source",
            str(source_dir),
            "--database",
            str(database_path),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "events_failed: 1" in result.stdout
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE name = 'UFC Fixture Two'"
        ).fetchone()[0] == 1
