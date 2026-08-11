import pytest

from src.app.config import AppConfig
from src.app.db import connect
from src.app.providers.odds import (
    OddsProviderAuthenticationError,
    OddsProviderNotFound,
    OddsProviderQuotaExceeded,
    OddsProviderResponseError,
    OddsProviderUnavailable,
    TheOddsAPIProvider,
    normalize_event,
)
from src.app.services.odds import import_provider_event, place_wager_from_snapshot
from src.server import create_app
from src.app.providers.odds.the_odds_api import HTTPResponse
import src.app.web as web_routes


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params), timeout))
        return self.responses.pop(0)


def odds_event_payload():
    return {
        "id": "event-123",
        "sport_key": "mma_mixed_martial_arts",
        "sport_title": "MMA",
        "commence_time": "2026-08-15T20:00:00-04:00",
        "home_team": "Fighter A",
        "away_team": "Fighter B",
        "bookmakers": [
            {
                "key": "book-one",
                "title": "Book One",
                "last_update": "2026-08-15T18:00:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Fighter A", "price": 125},
                            {"name": "Fighter B", "price": -145},
                        ],
                    }
                ],
            },
            {
                "key": "book-two",
                "title": "Book Two",
                "last_update": "2026-08-15T18:01:00Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Fighter A", "price": 130},
                            {"name": "Fighter B", "price": -150},
                        ],
                    }
                ],
            },
        ],
    }


def test_the_odds_api_normalizes_mma_events_and_american_moneylines():
    fake = FakeHTTP([HTTPResponse(200, {}, [odds_event_payload()])])
    provider = TheOddsAPIProvider("secret-key", http_get=fake.get)

    events = provider.upcoming_events()

    assert len(events) == 1
    event = events[0]
    assert event.provider_event_id == "event-123"
    assert event.commence_time == "2026-08-16T00:00:00Z"
    assert event.home_team == "Fighter A"
    assert event.bookmakers[0].outcomes[0].moneyline == 125
    assert fake.calls[0][0].endswith("/v4/sports/mma_mixed_martial_arts/odds")
    assert fake.calls[0][1]["markets"] == "h2h"
    assert fake.calls[0][1]["oddsFormat"] == "american"
    assert fake.calls[0][1]["dateFormat"] == "iso"


def test_missing_bookmakers_are_normalized_without_losing_the_event():
    payload = dict(odds_event_payload())
    payload["bookmakers"] = None

    event = normalize_event(payload)

    assert event.bookmakers == ()


def test_the_odds_api_normalizes_event_odds_and_scores():
    fake = FakeHTTP(
        [
            HTTPResponse(200, {}, odds_event_payload()),
            HTTPResponse(
                200,
                {},
                [
                    {
                        "id": "event-123",
                        "completed": True,
                        "scores": [
                            {"name": "Fighter A", "score": "2"},
                            {"name": "Fighter B", "score": "0"},
                        ],
                    }
                ],
            ),
        ]
    )
    provider = TheOddsAPIProvider("secret-key", http_get=fake.get)

    odds = provider.get_odds("event-123")
    result = provider.get_results("event-123")

    assert odds.bookmakers[1].outcomes[1].moneyline == -150
    assert result.status == "completed"
    assert result.winner == "Fighter A"
    assert fake.calls[1][0].endswith("/v4/sports/mma_mixed_martial_arts/scores")
    assert fake.calls[1][1]["daysFrom"] == "3"


def test_provider_classifies_missing_key_quota_and_not_found_errors():
    with pytest.raises(OddsProviderAuthenticationError):
        TheOddsAPIProvider(None).upcoming_events()

    quota = FakeHTTP(
        [
            HTTPResponse(
                429,
                {"x-requests-remaining": "0"},
                {"error_code": "EXCEEDED_FREQ_LIMIT", "message": "slow down"},
            )
        ]
    )
    with pytest.raises(OddsProviderQuotaExceeded) as quota_error:
        TheOddsAPIProvider("secret-key", http_get=quota.get).upcoming_events()
    assert quota_error.value.headers["x-requests-remaining"] == "0"

    not_found = FakeHTTP([HTTPResponse(404, {}, {"error_code": "EVENT_NOT_FOUND"})])
    with pytest.raises(OddsProviderNotFound):
        TheOddsAPIProvider("secret-key", http_get=not_found.get).get_odds("event-123")


def test_malformed_required_event_data_is_rejected():
    payload = odds_event_payload()
    payload["commence_time"] = "not-a-timestamp"

    with pytest.raises(OddsProviderResponseError):
        normalize_event(payload)


def test_provider_event_import_persists_external_identity_and_odds_snapshots(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    provider = TheOddsAPIProvider(
        "secret-key",
        http_get=FakeHTTP([]).get,
    )
    normalized = normalize_event(odds_event_payload())

    imported = import_provider_event(app.config["DATABASE_PATH"], normalized)
    repeated = import_provider_event(app.config["DATABASE_PATH"], normalized)

    assert imported.event_id == repeated.event_id
    assert imported.fight_id == repeated.fight_id
    with connect(app.config["DATABASE_PATH"]) as connection:
        event = connection.execute(
            "SELECT external_provider, external_id, status FROM events WHERE id = ?",
            (imported.event_id,),
        ).fetchone()
        fight = connection.execute(
            "SELECT fighter_a, fighter_b, scheduled_at, external_id FROM fights WHERE id = ?",
            (imported.fight_id,),
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM odds_snapshots WHERE fight_id = ?",
            (imported.fight_id,),
        ).fetchone()[0]

    assert tuple(event) == ("the_odds_api", "event-123", "draft")
    assert tuple(fight) == (
        "Fighter A",
        "Fighter B",
        "2026-08-16T00:00:00Z",
        "event-123",
    )
    assert snapshot_count == 4
    assert len(imported.odds_snapshot_ids) == 4
    assert provider.api_key == "secret-key"


def test_provider_transport_failures_are_classified_without_retrying_live_calls():
    def failed_request(url, params, timeout):
        raise OSError("network unavailable")

    with pytest.raises(OddsProviderUnavailable):
        TheOddsAPIProvider("secret-key", http_get=failed_request).upcoming_events()


def test_wager_from_snapshot_preserves_the_exact_moneyline_and_sportsbook(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    imported = import_provider_event(
        app.config["DATABASE_PATH"], normalize_event(odds_event_payload())
    )

    with connect(app.config["DATABASE_PATH"]) as connection:
        analyst_id = connection.execute(
            "SELECT id FROM analysts WHERE slug = 'theweasle'"
        ).fetchone()[0]
        snapshot = connection.execute(
            """
            SELECT id FROM odds_snapshots
            WHERE fight_id = ? AND fighter = 'Fighter A'
            ORDER BY id
            LIMIT 1
            """,
            (imported.fight_id,),
        ).fetchone()
        prediction_cursor = connection.execute(
            """
            INSERT INTO predictions(fight_id, analyst_id, picked_fighter, confidence)
            VALUES (?, ?, 'Fighter A', 70)
            """,
            (imported.fight_id, analyst_id),
        )
        prediction_id = prediction_cursor.lastrowid

    wager_id = place_wager_from_snapshot(
        app.config["DATABASE_PATH"],
        prediction_id=prediction_id,
        odds_snapshot_id=snapshot[0],
        stake_cents=50,
    )

    with connect(app.config["DATABASE_PATH"]) as connection:
        wager = connection.execute(
            "SELECT odds_snapshot_id, moneyline, sportsbook FROM wagers WHERE id = ?",
            (wager_id,),
        ).fetchone()

    assert tuple(wager) == (snapshot[0], 125, "Book One")


def test_imported_snapshot_survives_card_edit_and_is_linked_to_the_wager(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    imported = import_provider_event(
        app.config["DATABASE_PATH"], normalize_event(odds_event_payload())
    )
    client = app.test_client()

    response = client.post(
        f"/events/{imported.event_id}/edit",
        data={
            "promotion": "MMA",
            "name": "Fighter A vs Fighter B",
            "event_date": "2026-08-16",
            "fight_count": "15",
            "bout_order_1": "1",
            "fighter_a_1": "Fighter A",
            "fighter_b_1": "Fighter B",
            "analyst_1": "theweasle",
            "picked_fighter_1": "fighter_a",
            "confidence_1": "70",
            "predicted_method_1": "decision",
            "gender_1": "",
            "weight_class_1": "",
            "card_section_1": "",
            "moneyline_1": "125",
            "sportsbook_1": "Book One",
            "stake_1": "0.50",
            "odds_snapshot_1": str(imported.odds_snapshot_ids[0]),
        },
    )

    assert response.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        wager = connection.execute(
            """
            SELECT w.odds_snapshot_id, w.moneyline, w.sportsbook,
                   os.external_provider, os.fighter
            FROM wagers w
            JOIN odds_snapshots os ON os.id = w.odds_snapshot_id
            """
        ).fetchone()

    assert tuple(wager) == (wager[0], 125, "Book One", "the_odds_api", "Fighter A")


def test_import_odds_route_uses_provider_boundary_without_a_live_request(tmp_path, monkeypatch):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    normalized = normalize_event(odds_event_payload())

    class FakeProvider:
        def upcoming_events(self):
            return [normalized]

    monkeypatch.setattr(web_routes, "TheOddsAPIProvider", lambda *args, **kwargs: FakeProvider())

    response = app.test_client().post("/events/import")

    assert response.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
