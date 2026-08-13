from src.app.formatting import (
    format_american_date,
    format_height,
    format_reach,
    format_tape_value,
    format_weight_class,
)


def test_catalog_measurements_and_dates_are_user_friendly():
    assert format_height(70) == '5\'10"'
    assert format_height(72) == '6\'0"'
    assert format_reach(70.0) == "70 in"
    assert format_reach(70.5) == "71 in"
    assert format_american_date("1990-12-11") == "12/11/1990"
    assert format_tape_value("1990-12-11", "date_of_birth") == "12/11/1990"
    assert format_tape_value(70.0, "reach_inches") == "70 in"
    assert format_weight_class("Lightweight Bout") == "Lightweight"
