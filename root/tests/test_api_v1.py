from test_analytics import make_app, seed_analytics_data


def test_api_lists_analysts_and_events_with_stable_envelopes(tmp_path):
    app = make_app(tmp_path)
    first_event, _ = seed_analytics_data(app)
    client = app.test_client()

    analysts = client.get("/api/v1/analysts")
    events = client.get("/api/v1/events?limit=1")

    assert analysts.status_code == 200
    assert analysts.get_json()["meta"] == {
        "version": "v1",
        "limit": 50,
        "offset": 0,
        "count": 2,
        "total": 2,
        "has_more": False,
    }
    assert analysts.get_json()["data"] == [
        {
            "slug": "Analyst B".lower().replace(" ", ""),
            "name": "Analyst B",
            "source_type": "manual",
            "source_url": None,
            "active": True,
        },
        {
            "slug": "theweasle",
            "name": "TheWeasle",
            "source_type": "manual",
            "source_url": None,
            "active": True,
        },
    ]
    assert events.status_code == 200
    assert events.get_json()["meta"]["limit"] == 1
    assert events.get_json()["meta"]["total"] == 2
    assert events.get_json()["data"][0]["fight_count"] == 1
    assert events.get_json()["data"][0]["id"] != first_event


def test_api_event_and_analyst_detail_expose_no_private_odds_data(tmp_path):
    app = make_app(tmp_path)
    first_event, _ = seed_analytics_data(app)
    client = app.test_client()

    event_response = client.get(f"/api/v1/events/{first_event}")
    analyst_response = client.get("/api/v1/analysts/theweasle")

    assert event_response.status_code == 200
    event_data = event_response.get_json()["data"]
    assert event_data["name"] == "Analytics Card One"
    assert len(event_data["fights"]) == 3
    assert "moneyline" not in event_response.get_data(as_text=True)
    assert "sportsbook" not in event_response.get_data(as_text=True)
    assert analyst_response.get_json()["data"]["slug"] == "theweasle"


def test_api_picks_return_provenance_and_derived_results_without_wager_fields(tmp_path):
    app = make_app(tmp_path)
    first_event, _ = seed_analytics_data(app)
    client = app.test_client()

    response = client.get(f"/api/v1/events/{first_event}/picks?result=win")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["meta"]["total"] == 1
    pick = payload["data"][0]
    assert pick["analyst"]["slug"] == "theweasle"
    assert pick["prediction"]["fighter"] == "A"
    assert pick["prediction"]["result"] == "won"
    assert "source_url" in pick["prediction"]
    body = response.get_data(as_text=True)
    assert "moneyline" not in body
    assert "sportsbook" not in body
    assert "odds_snapshot" not in body
    assert "stake_cents" not in body


def test_api_analyst_picks_support_filters_and_pagination(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)
    client = app.test_client()

    response = client.get(
        "/api/v1/analysts/theweasle/picks"
        "?gender=female&weight_class=SW&card_section=prelim"
        "&confidence_min=50&confidence_max=70&underdog=true&limit=1"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["meta"] == {
        "version": "v1",
        "limit": 1,
        "offset": 0,
        "count": 1,
        "total": 1,
        "has_more": False,
    }
    assert payload["data"][0]["fight"]["gender"] == "female"
    assert payload["data"][0]["prediction"]["result"] == "lost"


def test_api_stats_use_private_odds_for_roi_without_exposing_them(tmp_path):
    app = make_app(tmp_path)
    seed_analytics_data(app)
    client = app.test_client()

    response = client.get("/api/v1/analysts/theweasle/stats")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["analyst"]["slug"] == "theweasle"
    assert data["sample_size"] == 3
    assert (data["wins"], data["losses"], data["pushes"]) == (1, 1, 1)
    assert data["accuracy"] == 0.5
    assert data["roi"] == -14 / 150
    assert "moneyline" not in response.get_data(as_text=True)
    assert "sportsbook" not in response.get_data(as_text=True)


def test_api_validation_and_not_found_errors_are_stable(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    invalid_limit = client.get("/api/v1/events?limit=201")
    invalid_event = client.get("/api/v1/events/not-an-id")
    missing_analyst = client.get("/api/v1/analysts/missing/stats")

    assert invalid_limit.status_code == 400
    assert invalid_limit.get_json() == {
        "error": {"code": "invalid_parameter", "message": "limit must be between 1 and 200"}
    }
    assert invalid_event.status_code == 400
    assert invalid_event.get_json()["error"]["code"] == "invalid_event_id"
    assert missing_analyst.status_code == 404
    assert missing_analyst.get_json() == {
        "error": {"code": "analyst_not_found", "message": "analyst not found"}
    }
