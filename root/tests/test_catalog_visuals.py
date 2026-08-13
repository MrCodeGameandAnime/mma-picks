from pathlib import Path

from test_ufc_catalog_web import _catalog_client


def test_catalog_visual_content_and_alignment(tmp_path):
    client, _, ids = _catalog_client(tmp_path)
    cards = client.get("/cards").get_data(as_text=True)
    detail = client.get(f"/cards/{ids['card_one']}").get_data(as_text=True)
    fight = client.get(f"/cards/{ids['card_one']}/fights/{ids['fight_one']}").get_data(as_text=True)
    fighter = client.get(f"/fighters/{ids['fighter']}").get_data(as_text=True)

    assert "UFCStats catalog" not in cards
    assert "08/10/2026" in cards
    assert "Las Vegas, Nevada, USA · 08/10/2026" in detail
    assert "UFCStats source" not in detail
    assert "Winner: Alpha One" in detail
    assert "Lightweight Bout" not in detail
    assert "Lightweight" in detail
    assert "UFC Fixture One · 2026-08-10" not in fight
    assert "UFCStats source" not in fighter


def test_eyebrow_markup_is_absent_from_all_templates_and_styles():
    template_dir = Path(__file__).parents[1] / "src" / "app" / "templates"
    assert not any("eyebrow" in path.read_text(encoding="utf-8") for path in template_dir.glob("*.html"))
    css = (Path(__file__).parents[1] / "src" / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".eyebrow" not in css
    assert ".catalog-card > div:last-child" in css
