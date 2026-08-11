from html.parser import HTMLParser

import httpx
import pytest

from src.app.config import AppConfig
from src.app.db import connect
from src.app.providers.odds import (
    OddsEvent,
    OddsOutcome,
    OddsProviderAuthenticationError,
    OddsProviderNotFound,
    OddsProviderQuotaExceeded,
    OddsProviderResponseError,
    OddsProviderUnavailable,
    QuotaInfo,
    TheOddsAPIProvider,
    normalize_event,
)
from src.app.providers.odds.the_odds_api import HTTPResponse
from src.app.services.events import FightInput, save_event
from src.app.services.odds import (
    OddsImportError,
    import_selected_bouts,
    place_wager_from_snapshot,
    refresh_odds_for_card,
)
from src.server import create_app
import src.app.web as web_routes


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params), timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FormStateParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.state = {}
        self.current_select = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name"):
            self.state[attributes["name"]] = attributes.get("value", "")
        elif tag == "select" and attributes.get("name"):
            self.current_select = attributes["name"]
        elif tag == "option" and self.current_select:
            value = attributes.get("value", "")
            self.state.setdefault(self.current_select, value)
            if "selected" in attributes:
                self.state[self.current_select] = value

    def handle_endtag(self, tag):
        if tag == "select":
            self.current_select = None


def rendered_form_state(html):
    parser = FormStateParser()
    parser.feed(html)
    return parser.state


def odds_event_payload(
    event_id="event-123",
    home_team="Fighter A",
    away_team="Fighter B",
    bookmakers=None,
):
    payload = {
        "id": event_id,
        "sport_key": "mma_mixed_martial_arts",
        "sport_title": "MMA",
        "commence_time": "2026-08-15T20:00:00-04:00",
        "home_team": home_team,
        "away_team": away_team,
    }
    if bookmakers is not None:
        payload["bookmakers"] = bookmakers
    return payload


def bookmakers(home="Fighter A", away="Fighter B", update="2026-08-15T18:00:00Z"):
    return [
        {
            "key": "book-one",
            "title": "Book One",
            "last_update": update,
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": home, "price": 125},
                        {"name": away, "price": -145},
                    ],
                }
            ],
        }
    ]


def normalized_event(event_id, home="Fighter A", away="Fighter B", update=None):
    return normalize_event(
        odds_event_payload(
            event_id,
            home,
            away,
            bookmakers(home, away, update) if update else None,
        )
    )


def make_card(app):
    return save_event(
        app.config["DATABASE_PATH"],
        promotion="UFC",
        name="UFC Test Card",
        event_date="2026-08-15",
        fights=[
            FightInput(
                "Manual A", "Manual B", None, None, None, 1,
                None, None, None, None, None, None, None,
            )
        ],
    )


def make_empty_card(app, name="Provider Card"):
    return save_event(
        app.config["DATABASE_PATH"],
        promotion="UFC",
        name=name,
        event_date="2026-08-15",
        fights=[],
        allow_empty=True,
    )


class FakeProvider:
    provider_name = "the_odds_api"

    def __init__(self, discoveries, odds):
        self.discoveries = discoveries
        self.odds = odds
        self.last_quota = QuotaInfo(remaining=91, used=9, last_cost=1)
        self.discover_calls = []
        self.odds_calls = []

    def discover_events(self, event_ids=None):
        self.discover_calls.append(tuple(event_ids) if event_ids is not None else None)
        if event_ids is None:
            return list(self.discoveries)
        wanted = set(event_ids)
        return [event for event in self.discoveries if event.provider_event_id in wanted]

    def fetch_odds(self, event_ids):
        self.odds_calls.append(tuple(event_ids))
        wanted = set(event_ids)
        return [event for event in self.odds if event.provider_event_id in wanted]


def test_discovery_uses_quota_free_events_endpoint_and_no_odds_request():
    fake = FakeHTTP([HTTPResponse(200, {}, [odds_event_payload()])])
    provider = TheOddsAPIProvider("secret-key", http_get=fake.get)

    events = provider.discover_events()

    assert len(events) == 1
    assert events[0].commence_time == "2026-08-16T00:00:00Z"
    assert events[0].bookmakers == ()
    assert fake.calls[0][0].endswith("/v4/sports/mma_mixed_martial_arts/events")
    assert all(not call[0].endswith("/odds") for call in fake.calls)
    assert fake.calls[0][1]["dateFormat"] == "iso"


def test_odds_request_is_batched_and_limited_to_selected_event_ids():
    fake = FakeHTTP(
        [HTTPResponse(200, {}, [odds_event_payload("event-1", bookmakers=bookmakers())])]
    )
    provider = TheOddsAPIProvider("secret-key", http_get=fake.get)

    events = provider.fetch_odds(["event-1", "event-3", "event-1"])

    assert len(events) == 1
    assert fake.calls[0][0].endswith("/v4/sports/mma_mixed_martial_arts/odds")
    assert fake.calls[0][1]["eventIds"] == "event-1,event-3"
    assert fake.calls[0][1]["markets"] == "h2h"
    assert fake.calls[0][1]["oddsFormat"] == "american"


def test_missing_bookmakers_are_normalized_without_losing_event():
    assert normalize_event(odds_event_payload()).bookmakers == ()


def test_malformed_required_event_data_is_rejected():
    payload = odds_event_payload()
    payload["commence_time"] = "not-a-timestamp"
    with pytest.raises(OddsProviderResponseError):
        normalize_event(payload)


def test_successful_response_captures_quota_headers():
    fake = FakeHTTP(
        [
            HTTPResponse(
                200,
                {
                    "x-requests-remaining": "42",
                    "x-requests-used": "8",
                    "x-requests-last": "1",
                },
                [],
            )
        ]
    )
    provider = TheOddsAPIProvider("secret-key", http_get=fake.get)

    provider.discover_events()

    assert provider.last_quota == QuotaInfo(remaining=42, used=8, last_cost=1)


def test_provider_classifies_auth_quota_and_not_found_errors():
    with pytest.raises(OddsProviderAuthenticationError):
        TheOddsAPIProvider(None).discover_events()

    quota = FakeHTTP(
        [HTTPResponse(429, {"x-requests-remaining": "0"}, {"error_code": "EXCEEDED_FREQ_LIMIT"})]
    )
    with pytest.raises(OddsProviderQuotaExceeded) as quota_error:
        TheOddsAPIProvider("secret-key", http_get=quota.get).discover_events()
    assert quota_error.value.quota == QuotaInfo(remaining=0)

    not_found = FakeHTTP([HTTPResponse(404, {}, {"error_code": "EVENT_NOT_FOUND"})])
    with pytest.raises(OddsProviderNotFound):
        TheOddsAPIProvider("secret-key", http_get=not_found.get).discover_events(["missing"])


def test_timeout_and_transport_failures_are_classified_without_retry():
    timeout = FakeHTTP([httpx.ReadTimeout("timed out")])
    with pytest.raises(OddsProviderUnavailable):
        TheOddsAPIProvider("secret-key", http_get=timeout.get).discover_events()
    assert len(timeout.calls) == 1

    failed = FakeHTTP([OSError("network unavailable")])
    with pytest.raises(OddsProviderUnavailable):
        TheOddsAPIProvider("secret-key", http_get=failed.get).discover_events()
    assert len(failed.calls) == 1


def test_mma_result_lookup_is_not_part_of_provider_contract():
    assert not hasattr(TheOddsAPIProvider("secret-key"), "get_results")


def test_selected_provider_bouts_share_one_user_card_and_unselected_bout_is_not_saved(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    discoveries = [normalized_event("bout-1"), normalized_event("bout-2", "C", "D"), normalized_event("bout-3", "E", "F")]
    odds = [normalized_event("bout-1", update="2026-08-15T18:00:00Z"), normalized_event("bout-3", "E", "F", "2026-08-15T18:01:00Z")]
    provider = FakeProvider(discoveries, odds)

    result = import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1", "bout-3"])

    assert result.event_id == card_id
    assert provider.discover_calls == [("bout-1", "bout-3")]
    assert provider.odds_calls == [("bout-1", "bout-3")]
    with connect(app.config["DATABASE_PATH"]) as connection:
        event = connection.execute("SELECT name, promotion, event_date, external_id FROM events WHERE id = ?", (card_id,)).fetchone()
        fights = connection.execute("SELECT external_id, bout_order FROM fights WHERE event_id = ? ORDER BY bout_order", (card_id,)).fetchall()
    assert tuple(event) == ("UFC Test Card", "UFC", "2026-08-15", None)
    assert [(row["external_id"], row["bout_order"]) for row in fights] == [(None, 1), ("bout-1", 2), ("bout-3", 3)]


def test_provider_import_failure_does_not_change_existing_card(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    provider = FakeProvider([], [])

    with pytest.raises(OddsImportError):
        import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["missing"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT name FROM events WHERE id = ?", (card_id,)).fetchone()[0] == "UFC Test Card"
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (card_id,)).fetchone()[0] == 1


def test_refresh_and_edit_preserve_provider_identity_without_duplicate(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    discovered = [normalized_event("bout-1")]
    provider = FakeProvider(discovered, [normalized_event("bout-1", update="2026-08-15T18:00:00Z")])
    imported = import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        old = connection.execute("SELECT id, scheduled_at FROM fights WHERE external_id = 'bout-1'").fetchone()

    save_event(
        app.config["DATABASE_PATH"],
        event_id=card_id,
        promotion="UFC",
        name="Renamed Card",
        event_date="2026-08-16",
        fights=[
            FightInput("Manual A", "Manual B", None, None, "early_prelim", 1, None, None, None, None, None, None, None),
            FightInput("Fighter A", "Fighter B", "lightweight", "male", "main_card", 2, None, None, None, None, None, None, None, fight_id=old["id"]),
        ],
    )
    refresh_odds_for_card(app.config["DATABASE_PATH"], card_id, provider)

    with connect(app.config["DATABASE_PATH"]) as connection:
        rows = connection.execute("SELECT id, external_provider, external_id, scheduled_at FROM fights WHERE event_id = ? AND external_id = 'bout-1'", (card_id,)).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0][1:]) == ("the_odds_api", "bout-1", old["scheduled_at"])
    assert rows[0]["id"] != imported.event_id


def test_exact_snapshot_selection_rejects_opponent_line_and_preserves_selected_line(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    provider_event = normalized_event("bout-1", update="2026-08-15T18:00:00Z")
    provider = FakeProvider([provider_event], [provider_event])
    imported = import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        analyst_id = connection.execute("SELECT id FROM analysts WHERE slug = 'theweasle'").fetchone()[0]
        fight_id = connection.execute("SELECT id FROM fights WHERE external_id = 'bout-1'").fetchone()[0]
        prediction_id = connection.execute("INSERT INTO predictions(fight_id, analyst_id, picked_fighter, confidence) VALUES (?, ?, 'Fighter A', 70)", (fight_id, analyst_id)).lastrowid
        opponent_snapshot = connection.execute("SELECT id FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter B'", (fight_id,)).fetchone()[0]
        picked_snapshot = connection.execute("SELECT id FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A'", (fight_id,)).fetchone()[0]

    with pytest.raises(OddsImportError):
        place_wager_from_snapshot(app.config["DATABASE_PATH"], prediction_id=prediction_id, odds_snapshot_id=opponent_snapshot, stake_cents=50)
    wager_id = place_wager_from_snapshot(app.config["DATABASE_PATH"], prediction_id=prediction_id, odds_snapshot_id=picked_snapshot, stake_cents=50)
    with connect(app.config["DATABASE_PATH"]) as connection:
        wager = connection.execute("SELECT odds_snapshot_id, moneyline, sportsbook FROM wagers WHERE id = ?", (wager_id,)).fetchone()
    assert tuple(wager) == (picked_snapshot, 125, "Book One")
    assert imported.odds_snapshot_ids


def test_stale_snapshots_are_kept_but_newest_remains_latest_and_wager_is_historical(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    newer = normalized_event("bout-1", update="2026-08-15T19:00:00Z")
    older = normalized_event("bout-1", update="2026-08-15T18:00:00Z")
    provider = FakeProvider([newer], [newer])
    import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        fight_id = connection.execute("SELECT id FROM fights WHERE external_id = 'bout-1'").fetchone()[0]
        analyst_id = connection.execute("SELECT id FROM analysts WHERE slug = 'theweasle'").fetchone()[0]
        prediction_id = connection.execute("INSERT INTO predictions(fight_id, analyst_id, picked_fighter, confidence) VALUES (?, ?, 'Fighter A', 70)", (fight_id, analyst_id)).lastrowid
        selected = connection.execute("SELECT id FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A'", (fight_id,)).fetchone()[0]
    place_wager_from_snapshot(app.config["DATABASE_PATH"], prediction_id=prediction_id, odds_snapshot_id=selected, stake_cents=50)
    provider.odds = [older]
    refresh_odds_for_card(app.config["DATABASE_PATH"], card_id, provider)
    with connect(app.config["DATABASE_PATH"]) as connection:
        snapshots = connection.execute("SELECT captured_at FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A' ORDER BY captured_at DESC", (fight_id,)).fetchall()
        wager = connection.execute("SELECT odds_snapshot_id, moneyline FROM wagers WHERE prediction_id = ?", (prediction_id,)).fetchone()
    assert [row[0] for row in snapshots] == ["2026-08-15T19:00:00Z", "2026-08-15T18:00:00Z"]
    assert tuple(wager) == (selected, 125)


def test_web_discovery_is_explicit_and_surfaces_quota_without_live_request(tmp_path, monkeypatch):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_card(app)
    provider_event = normalized_event("bout-1")
    provider = FakeProvider([provider_event], [normalized_event("bout-1", update="2026-08-15T18:00:00Z")])
    monkeypatch.setattr(web_routes, "TheOddsAPIProvider", lambda *args, **kwargs: provider)

    discovery = app.test_client().get(f"/events/{card_id}/provider-bouts")

    assert discovery.status_code == 200
    assert b"Quota: remaining 91, last request cost 1" in discovery.data
    assert provider.discover_calls == [None]
    assert provider.odds_calls == []

    imported = app.test_client().post(
        f"/events/{card_id}/provider-bouts",
        data={"provider_event_id": "bout-1"},
    )
    assert imported.status_code == 302
    assert provider.odds_calls == [("bout-1",)]


def test_empty_card_can_be_created_and_populated_entirely_through_provider_selection(tmp_path, monkeypatch):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    provider_events = [normalized_event("bout-1"), normalized_event("bout-2", "C", "D")]
    provider = FakeProvider(
        provider_events,
        [
            normalized_event("bout-1", update="2026-08-15T18:00:00Z"),
            normalized_event("bout-2", "C", "D", "2026-08-15T18:01:00Z"),
        ],
    )
    monkeypatch.setattr(web_routes, "TheOddsAPIProvider", lambda *args, **kwargs: provider)
    client = app.test_client()

    created = client.post(
        "/events/new",
        data={
            "promotion": "UFC",
            "name": "Empty Provider Card",
            "event_date": "2026-08-15",
            "fight_count": "15",
        },
    )
    assert created.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        card = connection.execute("SELECT id, status FROM events WHERE name = 'Empty Provider Card'").fetchone()
        assert tuple(card) == (1, "draft")
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (card["id"],)).fetchone()[0] == 0

    settlement = client.post(f"/events/{card['id']}/settle", follow_redirects=True)
    assert b"an event needs at least one fight before settlement" in settlement.data

    assert client.get(f"/events/{card['id']}/provider-bouts").status_code == 200
    imported = client.post(
        f"/events/{card['id']}/provider-bouts",
        data={"provider_event_id": ["bout-1", "bout-2"]},
    )
    assert imported.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        fights = connection.execute(
            "SELECT external_id FROM fights WHERE event_id = ? ORDER BY bout_order",
            (card["id"],),
        ).fetchall()
    assert [row[0] for row in fights] == ["bout-1", "bout-2"]


def test_provider_import_respects_configured_capacity_before_paid_odds_request(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_empty_card(app, "Capacity Card")
    discoveries = [normalized_event(f"bout-{index}", f"A{index}", f"B{index}") for index in range(1, 17)]
    odds = [normalized_event(f"bout-{index}", f"A{index}", f"B{index}", f"2026-08-15T18:{index:02d}:00Z") for index in range(1, 17)]
    provider = FakeProvider(discoveries, odds)

    import_selected_bouts(
        app.config["DATABASE_PATH"],
        card_id,
        provider,
        [f"bout-{index}" for index in range(1, 16)],
    )
    assert len(provider.odds_calls) == 1
    with pytest.raises(OddsImportError, match="more than 15"):
        import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-16"])

    assert len(provider.odds_calls) == 1
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (card_id,)).fetchone()[0] == 15


def test_new_provider_fight_demotes_upcoming_card_but_reimport_does_not(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_empty_card(app, "Lifecycle Card")
    provider_event = normalized_event("bout-1", update="2026-08-15T18:00:00Z")
    provider = FakeProvider([provider_event], [provider_event])

    import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        fight = connection.execute("SELECT id FROM fights WHERE external_id = 'bout-1'").fetchone()
        analyst_id = connection.execute("SELECT id FROM analysts WHERE slug = 'theweasle'").fetchone()[0]
        snapshot_id = connection.execute("SELECT id FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A'", (fight[0],)).fetchone()[0]
    save_event(
        app.config["DATABASE_PATH"],
        event_id=card_id,
        promotion="UFC",
        name="Lifecycle Card",
        event_date="2026-08-15",
        fights=[FightInput("Fighter A", "Fighter B", None, None, None, 1, analyst_id, "Fighter A", 70, "decision", None, None, 50, snapshot_id, fight[0])],
    )
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (card_id,)).fetchone()[0] == "upcoming"

    import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        assert connection.execute("SELECT status FROM events WHERE id = ?", (card_id,)).fetchone()[0] == "upcoming"


def test_provider_identity_and_snapshots_follow_stable_ids_when_bout_orders_swap(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_empty_card(app, "Reorder Card")
    provider_events = [normalized_event("bout-1"), normalized_event("bout-2", "C", "D")]
    provider = FakeProvider(
        provider_events,
        [normalized_event("bout-1", update="2026-08-15T18:00:00Z"), normalized_event("bout-2", "C", "D", "2026-08-15T18:01:00Z")],
    )
    import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1", "bout-2"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        fights = connection.execute("SELECT id, external_id, fighter_a, fighter_b, bout_order FROM fights WHERE event_id = ? ORDER BY external_id", (card_id,)).fetchall()
        original_snapshot = connection.execute("SELECT fight_id, fighter, sportsbook, moneyline, captured_at FROM odds_snapshots WHERE fight_id = ? AND fighter = ?", (fights[0]["id"], fights[0]["fighter_a"])).fetchone()

    client = app.test_client()
    response = client.post(
        f"/events/{card_id}/edit",
        data={
            "fight_count": "15",
            "promotion": "UFC",
            "name": "Reorder Card",
            "event_date": "2026-08-15",
            "fight_id_1": str(fights[1]["id"]),
            "bout_order_1": "1",
            "fighter_a_1": fights[1]["fighter_a"],
            "fighter_b_1": fights[1]["fighter_b"],
            "fight_id_2": str(fights[0]["id"]),
            "bout_order_2": "2",
            "fighter_a_2": fights[0]["fighter_a"],
            "fighter_b_2": fights[0]["fighter_b"],
        },
    )
    assert response.status_code == 302
    refresh_odds_for_card(app.config["DATABASE_PATH"], card_id, provider)
    with connect(app.config["DATABASE_PATH"]) as connection:
        refreshed = connection.execute("SELECT external_id, fighter_a, fighter_b, bout_order FROM fights WHERE event_id = ? ORDER BY bout_order", (card_id,)).fetchall()
        current_snapshot = connection.execute("SELECT fighter, sportsbook, moneyline, captured_at FROM odds_snapshots WHERE fight_id = (SELECT id FROM fights WHERE external_id = 'bout-1') AND fighter = 'Fighter A' ORDER BY captured_at DESC, id DESC LIMIT 1").fetchone()
    assert [(row[0], row[1], row[2]) for row in refreshed] == [("bout-2", "C", "D"), ("bout-1", "Fighter A", "Fighter B")]
    assert tuple(current_snapshot) == tuple(original_snapshot[1:])
    assert len(refreshed) == 2


def test_selected_provider_snapshot_and_edit_state_survive_browser_validation_round_trip(tmp_path):
    app = create_app(AppConfig(database_path=tmp_path / "tracker.db"))
    card_id = make_empty_card(app, "Snapshot Form Card")
    provider_event = normalized_event("bout-1", update="2026-08-15T18:00:00Z")
    provider = FakeProvider([provider_event], [provider_event])
    import_selected_bouts(app.config["DATABASE_PATH"], card_id, provider, ["bout-1"])
    with connect(app.config["DATABASE_PATH"]) as connection:
        fight = connection.execute("SELECT * FROM fights WHERE external_id = 'bout-1'").fetchone()
        analyst_id = connection.execute("SELECT id FROM analysts WHERE slug = 'theweasle'").fetchone()[0]
        snapshot = connection.execute("SELECT * FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A'", (fight["id"],)).fetchone()
    save_event(
        app.config["DATABASE_PATH"],
        event_id=card_id,
        promotion="UFC",
        name="Snapshot Form Card",
        event_date="2026-08-15",
        fights=[FightInput("Fighter A", "Fighter B", None, None, None, 1, analyst_id, "Fighter A", 70, "decision", None, None, 50, snapshot["id"], fight["id"])],
    )
    with connect(app.config["DATABASE_PATH"]) as connection:
        current_fight = connection.execute("SELECT * FROM fights WHERE external_id = 'bout-1'").fetchone()
        current_snapshot = connection.execute("SELECT * FROM odds_snapshots WHERE fight_id = ? AND fighter = 'Fighter A'", (current_fight["id"],)).fetchone()

    client = app.test_client()
    initial_state = rendered_form_state(client.get(f"/events/{card_id}/edit").get_data(as_text=True))
    assert initial_state["fight_id_1"] == str(current_fight["id"])
    assert initial_state["picked_fighter_1"] == "fighter_a"
    assert initial_state["analyst_1"] == "theweasle"
    assert initial_state["odds_snapshot_1"] == str(current_snapshot["id"])

    invalid_data = dict(initial_state)
    invalid_data["confidence_1"] = "101"
    invalid = client.post(f"/events/{card_id}/edit", data=invalid_data)
    assert invalid.status_code == 200
    invalid_html = invalid.get_data(as_text=True)
    invalid_state = rendered_form_state(invalid_html)
    assert invalid_state["fight_id_1"] == str(current_fight["id"])
    assert invalid_state["picked_fighter_1"] == "fighter_a"
    assert invalid_state["analyst_1"] == "theweasle"
    assert invalid_state["odds_snapshot_1"] == str(current_snapshot["id"])
    assert '<option value="fighter_a" selected>' in invalid_html
    assert f'<option value="{current_snapshot["id"]}" selected>' in invalid_html

    corrected_data = dict(invalid_state)
    corrected_data["confidence_1"] = "70"
    corrected_data["name"] = "Snapshot Form Card Updated"
    saved = client.post(f"/events/{card_id}/edit", data=corrected_data)
    assert saved.status_code == 302
    with connect(app.config["DATABASE_PATH"]) as connection:
        fights = connection.execute("SELECT id, external_provider, external_id, fighter_a, fighter_b FROM fights WHERE event_id = ?", (card_id,)).fetchall()
        wager = connection.execute(
            """
            SELECT os.external_provider, os.fighter, os.sportsbook, os.moneyline, os.captured_at
            FROM wagers w JOIN odds_snapshots os ON os.id = w.odds_snapshot_id
            """
        ).fetchone()
        fight_count = connection.execute("SELECT COUNT(*) FROM fights WHERE event_id = ?", (card_id,)).fetchone()[0]
    assert len(fights) == 1
    assert tuple(fights[0][1:]) == ("the_odds_api", "bout-1", "Fighter A", "Fighter B")
    assert tuple(wager) == ("the_odds_api", "Fighter A", "Book One", 125, "2026-08-15T18:00:00Z")
    assert fight_count == 1
