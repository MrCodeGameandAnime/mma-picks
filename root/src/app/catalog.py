from __future__ import annotations

from flask import Blueprint, current_app, render_template, request

from .services.ufc_catalog import get_card, get_fighter, get_fight, list_cards


catalog = Blueprint("catalog", __name__)


def _page_number() -> int | None:
    raw = request.args.get("page", "1")
    try:
        page = int(raw)
    except ValueError:
        return None
    return page if page > 0 else None


@catalog.get("/cards")
def cards():
    page = _page_number()
    if page is None:
        return "Page not found", 404
    result = list_cards(current_app.config["DATABASE_PATH"], page=page)
    if result["page_count"] and page > result["page_count"]:
        return "Page not found", 404
    return render_template("cards.html", **result)


@catalog.get("/cards/<int:event_id>")
def card_detail(event_id: int):
    card = get_card(current_app.config["DATABASE_PATH"], event_id)
    if card is None:
        return "Card not found", 404
    return render_template("card_detail.html", card=card)


@catalog.get("/cards/<int:event_id>/fights/<int:fight_id>")
def fight_detail(event_id: int, fight_id: int):
    fight = get_fight(current_app.config["DATABASE_PATH"], event_id, fight_id)
    if fight is None:
        return "Fight not found", 404
    return render_template("fight_detail.html", fight=fight)


@catalog.get("/fighters/<int:fighter_id>")
def fighter_detail(fighter_id: int):
    fighter = get_fighter(current_app.config["DATABASE_PATH"], fighter_id)
    if fighter is None:
        return "Fighter not found", 404
    return render_template("fighter_detail.html", fighter=fighter)
