from __future__ import annotations

import re

import pytest

from src.app.config import AppConfig
from src.app.db import connect
from src.app.providers.picks import (
    NormalizedPick,
    PicksProviderUnavailable,
    UnsupportedPicksProvider,
)
from src.app.services.events import FightInput, save_event
from src.app.services.picks import PicksImportError, ingest_from_provider, ingest_picks
from src.app.services.public_api import PublicPickFilters, load_public_picks
from src.server import create_app


CANONICAL_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FixturePicksProvider:
    name = "fixture"

    def __init__(self, picks):
        self.picks = list(picks)
        self.calls = []

    def fetch_picks(self, analyst_slug, *, event_name=None, event_date=None):
        self.calls.append((analyst_slug, event_name, event_date))
        return self.picks


def make_app(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    app.config.update(TESTING=True)
    return app


def fight_input(
    fighter_a,
    fighter_b,
    *,
    analyst_id=None,
    picked_fighter=None,
    confidence=60,
    predicted_method="decision",
    bout_order=1,
    fight_id=None,
):
    return FightInput(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        weight_class="WW",
        gender="male",
        card_section="main_card",
        bout_order=bout_order,
        analyst_id=analyst_id,
        picked_fighter=picked_fighter,
        confidence=confidence if picked_fighter else None,
        predicted_method=predicted_method if picked_fighter else None,
        sportsbook=None,
        moneyline=None,
        stake_cents=None,
        fight_id=fight_id,
    )


def create_card(database_path, *fights):
    return save_event(
        database_path,
        promotion="UFC",
        name="Provider Source Card",
        event_date="2026-08-15",
        fights=list(fights),
    )


def pick(
    fighter_a,
    fighter_b,
    *,
    identifier="video-123",
    published_at="2026-08-10T12:00:00+00:00",
    picked_fighter=None,
    confidence=80,
    predicted_method="decision",
):
    return NormalizedPick(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        picked_fighter=fighter_a if picked_fighter is None else picked_fighter,
        confidence=confidence,
        predicted_method=predicted_method,
        source_identifier=identifier,
        source_url=f"https://www.youtube.com/watch?v={identifier}",
        published_at=published_at,
    )


def source_edit_context(database_path, event_id):
    with connect(database_path) as connection:
        fight = connection.execute(
            "SELECT id, fighter_a, fighter_b FROM fights WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        analyst_id = connection.execute(
            "SELECT id FROM analysts WHERE slug = 'theweasle'"
        ).fetchone()[0]
    return fight, analyst_id


def edit_prediction(
    database_path,
    event_id,
    fight,
    analyst_id,
    *,
    confidence=80,
    predicted_method="decision",
):
    save_event(
        database_path,
        promotion="UFC",
        name="Provider Source Card Edited",
        event_date="2026-08-16",
        event_id=event_id,
        fights=[
            fight_input(
                fight["fighter_a"],
                fight["fighter_b"],
                analyst_id=analyst_id,
                picked_fighter=fight["fighter_a"],
                confidence=confidence,
                predicted_method=predicted_method,
                fight_id=fight["id"],
            )
        ],
    )


def test_provider_ingestion_persists_normalized_pick_provenance(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    provider = FixturePicksProvider([pick("Alpha", "Beta")])

    prediction_ids = ingest_from_provider(
        database_path,
        event_id,
        "theweasle",
        provider,
        event_name="Provider Source Card",
        event_date="2026-08-15",
    )

    assert provider.calls == [("theweasle", "Provider Source Card", "2026-08-15")]
    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT * FROM predictions WHERE id = ?", (prediction_ids[0],)
        ).fetchone()
    assert prediction["picked_fighter"] == "Alpha"
    assert prediction["source_identifier"] == "video-123"
    assert prediction["source_url"] == "https://www.youtube.com/watch?v=video-123"
    assert prediction["source_published_at"] == "2026-08-10T12:00:00Z"
    assert CANONICAL_UTC.fullmatch(prediction["captured_at"])
    public_pick = load_public_picks(
        database_path,
        PublicPickFilters(),
        analyst_slug="theweasle",
        event_id=event_id,
    )[0]
    assert public_pick["source_identifier"] == "video-123"


def test_public_api_route_exposes_source_identifier_without_private_wager_data(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    ingest_picks(
        database_path,
        event_id,
        "theweasle",
        [pick("Alpha", "Beta")],
        provider_name="fixture",
    )

    response = app.test_client().get(f"/api/v1/events/{event_id}/picks")

    assert response.status_code == 200
    assert response.get_json()["data"][0]["prediction"]["source_identifier"] == "video-123"
    body = response.get_data(as_text=True)
    for private_field in ("moneyline", "sportsbook", "stake", "stake_cents", "odds_snapshot"):
        assert private_field not in body


def test_same_source_can_be_reimported_idempotently(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    source_pick = pick("Alpha", "Beta")

    first = ingest_picks(
        database_path,
        event_id,
        "theweasle",
        [source_pick],
        provider_name="fixture",
    )
    with connect(database_path) as connection:
        captured_at = connection.execute(
            "SELECT captured_at FROM predictions WHERE id = ?", (first[0],)
        ).fetchone()[0]
    second = ingest_picks(
        database_path,
        event_id,
        "theweasle",
        [source_pick],
        provider_name="fixture",
    )

    assert second == first
    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
        assert connection.execute(
            "SELECT captured_at FROM predictions WHERE id = ?", (first[0],)
        ).fetchone()[0] == captured_at


def _ingest_and_read_prediction(tmp_path, source_pick):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    ingest_picks(
        database_path,
        event_id,
        "theweasle",
        [source_pick],
        provider_name="fixture",
    )
    with connect(database_path) as connection:
        before = dict(connection.execute("SELECT * FROM predictions").fetchone())
    return database_path, event_id, before


def _assert_reimport_payload_conflict(tmp_path, source_pick, changed_pick):
    database_path, event_id, before = _ingest_and_read_prediction(tmp_path, source_pick)

    with pytest.raises(PicksImportError, match="source payload changed"):
        ingest_picks(
            database_path,
            event_id,
            "theweasle",
            [changed_pick],
            provider_name="fixture",
        )

    with connect(database_path) as connection:
        after = dict(connection.execute("SELECT * FROM predictions").fetchone())
    assert after == before


def test_same_source_with_changed_confidence_is_not_idempotent(tmp_path):
    source_pick = pick("Alpha", "Beta")
    _assert_reimport_payload_conflict(
        tmp_path,
        source_pick,
        pick("Alpha", "Beta", confidence=60),
    )


def test_same_source_with_changed_fighter_is_not_idempotent(tmp_path):
    source_pick = pick("Alpha", "Beta")
    _assert_reimport_payload_conflict(
        tmp_path,
        source_pick,
        pick("Alpha", "Beta", picked_fighter="Beta"),
    )


def test_same_source_with_changed_method_is_not_idempotent(tmp_path):
    source_pick = pick("Alpha", "Beta")
    _assert_reimport_payload_conflict(
        tmp_path,
        source_pick,
        pick("Alpha", "Beta", predicted_method="KO/TKO"),
    )


def test_same_source_with_changed_publication_time_is_not_idempotent(tmp_path):
    source_pick = pick("Alpha", "Beta")
    _assert_reimport_payload_conflict(
        tmp_path,
        source_pick,
        pick("Alpha", "Beta", published_at="2026-08-10T13:00:00+00:00"),
    )


def test_card_edit_preserves_automated_prediction_provenance(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    ingest_picks(
        database_path,
        event_id,
        "theweasle",
        [pick("Alpha", "Beta")],
        provider_name="fixture",
    )

    with connect(database_path) as connection:
        captured_at = connection.execute(
            "SELECT captured_at FROM predictions"
        ).fetchone()[0]
    fight, analyst_id = source_edit_context(database_path, event_id)
    edit_prediction(database_path, event_id, fight, analyst_id)

    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT source_identifier, source_url, source_published_at, captured_at FROM predictions"
        ).fetchone()
    assert prediction["source_identifier"] == "video-123"
    assert prediction["source_url"] == "https://www.youtube.com/watch?v=video-123"
    assert prediction["source_published_at"] == "2026-08-10T12:00:00Z"
    assert prediction["captured_at"] == captured_at


def test_changed_confidence_clears_automated_prediction_provenance(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    ingest_picks(database_path, event_id, "theweasle", [pick("Alpha", "Beta")], provider_name="fixture")
    fight, analyst_id = source_edit_context(database_path, event_id)
    monkeypatch.setattr("src.app.services.events.utc_now", lambda: "2026-08-12T00:00:00Z")

    edit_prediction(database_path, event_id, fight, analyst_id, confidence=60)

    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT source_identifier, source_url, source_published_at, captured_at, confidence FROM predictions"
        ).fetchone()
    assert prediction["confidence"] == 60
    assert prediction["source_identifier"] is None
    assert prediction["source_url"] is None
    assert prediction["source_published_at"] is None
    assert prediction["captured_at"] == "2026-08-12T00:00:00Z"


def test_changed_predicted_method_clears_automated_prediction_provenance(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    ingest_picks(database_path, event_id, "theweasle", [pick("Alpha", "Beta")], provider_name="fixture")
    fight, analyst_id = source_edit_context(database_path, event_id)
    monkeypatch.setattr("src.app.services.events.utc_now", lambda: "2026-08-12T00:01:00Z")

    edit_prediction(database_path, event_id, fight, analyst_id, predicted_method="KO/TKO")

    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT source_identifier, source_url, source_published_at, captured_at, predicted_method FROM predictions"
        ).fetchone()
    assert prediction["predicted_method"] == "KO/TKO"
    assert prediction["source_identifier"] is None
    assert prediction["source_url"] is None
    assert prediction["source_published_at"] is None
    assert prediction["captured_at"] == "2026-08-12T00:01:00Z"


def test_provider_import_does_not_replace_manual_prediction(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    with connect(database_path) as connection:
        analyst_id = connection.execute(
            "SELECT id FROM analysts WHERE slug = 'theweasle'"
        ).fetchone()[0]
    event_id = create_card(
        database_path,
        fight_input("Alpha", "Beta", analyst_id=analyst_id, picked_fighter="Beta"),
    )

    with pytest.raises(PicksImportError, match="prediction already exists"):
        ingest_picks(
            database_path,
            event_id,
            "theweasle",
            [pick("Alpha", "Beta")],
            provider_name="fixture",
        )

    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT picked_fighter, source_identifier FROM predictions"
        ).fetchone()
    assert prediction["picked_fighter"] == "Beta"
    assert prediction["source_identifier"] is None


def test_provider_import_is_atomic_when_a_later_pick_cannot_match(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(
        database_path,
        fight_input("Alpha", "Beta"),
        fight_input("Gamma", "Delta", bout_order=2),
    )
    second = pick("Missing", "Opponent", identifier="video-456")

    with pytest.raises(PicksImportError, match="does not match"):
        ingest_picks(
            database_path,
            event_id,
            "theweasle",
            [pick("Alpha", "Beta"), second],
            provider_name="fixture",
        )

    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_unsupported_external_source_leaves_manual_entry_available(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    with pytest.raises(PicksProviderUnavailable):
        UnsupportedPicksProvider().fetch_picks("theweasle")

    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    with connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM fights WHERE event_id = ?", (event_id,)
        ).fetchone()[0] == 1


def test_invalid_source_timestamp_is_rejected_without_persistence(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]
    event_id = create_card(database_path, fight_input("Alpha", "Beta"))
    invalid = pick("Alpha", "Beta", published_at="2026-08-10T12:00:00")

    with pytest.raises(PicksImportError, match="publication timestamp"):
        ingest_picks(
            database_path,
            event_id,
            "theweasle",
            [invalid],
            provider_name="fixture",
        )

    with connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0
