from src.app.services.ufc_catalog_import import sync_catalog

from test_expansion_a_parser_isolation import _assert_only_second_event, _copy_source


def test_directory_sync_isolates_malformed_event_row(tmp_path):
    source_dir = _copy_source(tmp_path)
    events = source_dir / "ufc_event_details.csv"
    events.write_text(
        events.read_text(encoding="utf-8").replace(
            "August 10, 2026",
            "not-a-date",
            1,
        ),
        encoding="utf-8",
    )
    database_path = tmp_path / "tracker.db"
    summary = sync_catalog(database_path, source_dir)
    _assert_only_second_event(database_path, summary)
    assert any("event line" in error for error in summary.errors)
