from src.app.analytics import (
    AnalyticsFilters,
    analytics_report,
    apply_filters,
    bankroll_history,
    load_prediction_frame,
    summarize_performance,
)
from src.app.config import AppConfig
from src.app.db import connect
from src.app.services.events import FightInput, save_event
from src.app.services.settlement import settle_event
from src.server import create_app


def make_app(tmp_path):
    return create_app(AppConfig(database_path=tmp_path / "tracker.db"))


def make_fight(
    fighter_a,
    fighter_b,
    *,
    bout_order,
    analyst_id,
    pick,
    confidence,
    moneyline,
    gender,
    weight_class,
    card_section,
):
    return FightInput(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        weight_class=weight_class,
        gender=gender,
        card_section=card_section,
        bout_order=bout_order,
        analyst_id=analyst_id,
        picked_fighter=pick,
        confidence=confidence,
        predicted_method="decision",
        sportsbook="TestBook",
        moneyline=moneyline,
        stake_cents=50,
    )


def seed_analytics_data(app):
    database_path = app.config["DATABASE_PATH"]
    with connect(database_path) as connection:
        connection.execute(
            "INSERT INTO analysts(slug, name, source_type, active) VALUES (?, ?, 'manual', 1)",
            ("analystb", "Analyst B"),
        )
        analyst_b = connection.execute(
            "SELECT id FROM analysts WHERE slug = 'analystb'"
        ).fetchone()[0]

    first_event = save_event(
        database_path,
        promotion="UFC",
        name="Analytics Card One",
        event_date="2026-08-10",
        fights=[
            make_fight(
                "A", "B", bout_order=1, analyst_id=1, pick="A", confidence=80,
                moneyline=-140, gender="male", weight_class="WW", card_section="main_card",
            ),
            make_fight(
                "C", "D", bout_order=2, analyst_id=1, pick="D", confidence=60,
                moneyline=130, gender="female", weight_class="SW", card_section="prelim",
            ),
            make_fight(
                "E", "F", bout_order=3, analyst_id=1, pick="E", confidence=40,
                moneyline=-110, gender="male", weight_class="LW", card_section="early_prelim",
            ),
        ],
    )
    second_event = save_event(
        database_path,
        promotion="UFC",
        name="Analytics Card Two",
        event_date="2026-08-20",
        fights=[
            make_fight(
                "G", "H", bout_order=1, analyst_id=analyst_b, pick="H", confidence=70,
                moneyline=120, gender="female", weight_class="SW", card_section="main_card",
            )
        ],
    )

    with connect(database_path) as connection:
        first_fights = [
            row[0]
            for row in connection.execute(
                "SELECT id FROM fights WHERE event_id = ? ORDER BY bout_order",
                (first_event,),
            )
        ]
        second_fight = connection.execute(
            "SELECT id FROM fights WHERE event_id = ?", (second_event,)
        ).fetchone()[0]
    settle_event(
        database_path,
        first_event,
        {
            first_fights[0]: "A",
            first_fights[1]: "C",
            first_fights[2]: "draw",
        },
    )
    settle_event(database_path, second_event, {second_fight: "G"})
    return first_event, second_event


def test_load_prediction_frame_normalizes_results_and_analytics_dimensions(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)

    frame = load_prediction_frame(app.config["DATABASE_PATH"])

    assert len(frame) == 4
    assert set(frame["prediction_result"]) == {"won", "lost", "push"}
    assert set(frame["confidence_band"]) == {"0-49", "50-74", "75-100"}
    assert set(frame["favorite_status"]) == {"favorite", "underdog"}
    assert set(frame["gender"]) == {"male", "female"}


def test_summary_reports_accuracy_roi_and_sample_sizes(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)

    report = analytics_report(app.config["DATABASE_PATH"])
    summary = report["summary"]

    assert summary["sample_size"] == 4
    assert summary["wager_sample_size"] == 4
    assert (summary["wins"], summary["losses"], summary["pushes"]) == (1, 2, 1)
    assert summary["total_wagered_cents"] == 200
    assert summary["net_profit_cents"] == -64
    assert summary["roi"] == -0.32
    assert summary["accuracy"] == 1 / 3
    assert summary["current_bankroll_cents"] == 686

    analysts = {row["group"]: row for row in report["by_analyst"]}
    assert analysts["theweasle"]["sample_size"] == 3
    assert analysts["theweasle"]["wins"] == 1
    assert analysts["analystb"]["analyst_name"] == "Analyst B"
    assert analysts["analystb"]["sample_size"] == 1


def test_filters_support_subgroups_confidence_odds_result_and_dates(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)
    database_path = app.config["DATABASE_PATH"]

    filtered = analytics_report(
        database_path,
        AnalyticsFilters(
            gender="female",
            weight_class="SW",
            card_section="prelim",
            confidence_band="50-74",
            odds_min=100,
            odds_max=150,
            favorite="underdog",
            result="lost",
            date_from="2026-08-01",
            date_to="2026-08-15",
        ),
    )

    summary = filtered["summary"]
    assert summary["sample_size"] == 1
    assert summary["wager_sample_size"] == 1
    assert summary["wins"] == 0
    assert summary["losses"] == 1
    assert summary["roi"] == -1.0
    assert filtered["filters"]["result"] == "lost"

    by_section = filtered["by_card_section"]
    assert len(by_section) == 1
    assert by_section[0]["group"] == "prelim"
    assert by_section[0]["sample_size"] == 1


def test_bankroll_history_tracks_peak_and_drawdown_in_settlement_order(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)
    frame = load_prediction_frame(app.config["DATABASE_PATH"])

    history = bankroll_history(frame, 750)

    assert [row["profit_cents"] for row in history] == [36, -50, 0, -50]
    assert [row["bankroll_cents"] for row in history] == [786, 736, 736, 686]
    assert [row["peak_bankroll_cents"] for row in history] == [786, 786, 786, 786]
    assert [row["drawdown_cents"] for row in history] == [0, 50, 50, 100]


def test_empty_and_pending_data_has_zero_sample_without_failure(tmp_path):
    app = make_app(tmp_path)
    database_path = app.config["DATABASE_PATH"]

    frame = load_prediction_frame(database_path)
    assert frame.empty
    assert summarize_performance(frame)["sample_size"] == 0
    report = analytics_report(database_path)
    assert report["summary"]["current_bankroll_cents"] == 750
    assert report["summary"]["maximum_drawdown_cents"] == 0
    assert report["bankroll_history"] == []


def test_analytics_route_applies_query_filters(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)

    response = app.test_client().get("/analytics?analyst=theweasle&gender=female")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Performance by analyst" in body
    assert "Sample size" in body
    assert "50.0%" in body or "0.0%" in body
