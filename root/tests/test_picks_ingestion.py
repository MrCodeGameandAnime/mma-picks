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
        confidence=60 if picked_fighter else None,
        predicted_method="decision" if picked_fighter else None,
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


def pick(fighter_a, fighter_b, *, identifier="video-123", published_at="2026-08-10T12:00:00+00:00"):
    return NormalizedPick(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        picked_fighter=fighter_a,
        confidence=80,
        predicted_method="decision",
        source_identifier=identifier,
        source_url=f"https://www.youtube.com/watch?v={identifier}",
        published_at=published_at,
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
        fight = connection.execute(
            "SELECT id FROM fights WHERE event_id = ?", (event_id,)
        ).fetchone()
        analyst_id = connection.execute(
            "SELECT id FROM analysts WHERE slug = 'theweasle'"
        ).fetchone()[0]
    save_event(
        database_path,
        promotion="UFC",
        name="Provider Source Card Edited",
        event_date="2026-08-16",
        event_id=event_id,
        fights=[
            fight_input(
                "Alpha",
                "Beta",
                analyst_id=analyst_id,
                picked_fighter="Alpha",
                fight_id=fight["id"],
            )
        ],
    )

    with connect(database_path) as connection:
        prediction = connection.execute(
            "SELECT source_identifier, source_url, source_published_at FROM predictions"
        ).fetchone()
    assert prediction["source_identifier"] == "video-123"
    assert prediction["source_url"] == "https://www.youtube.com/watch?v=video-123"
    assert prediction["source_published_at"] == "2026-08-10T12:00:00Z"


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
