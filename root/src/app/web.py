from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .metrics import dashboard_metrics
from .providers.odds import OddsProviderError, QuotaInfo, TheOddsAPIProvider
from .services.events import (
    ValidationError,
    get_analysts,
    get_event,
    get_tracker_settings,
    list_events,
    parse_fights,
    save_event,
)
from .services.settlement import settle_event
from .services.odds import OddsImportError, import_selected_bouts, refresh_odds_for_card


web = Blueprint("web", __name__)


@web.get("/")
def home():
    database_path = current_app.config["DATABASE_PATH"]
    return render_template(
        "dashboard.html",
        metrics=dashboard_metrics(database_path),
        recent_events=list_events(database_path)[:5],
    )


@web.get("/events")
def events():
    return render_template(
        "events.html",
        events=list_events(current_app.config["DATABASE_PATH"]),
    )


def _odds_provider() -> TheOddsAPIProvider:
    return TheOddsAPIProvider(
        current_app.config.get("ODDS_API_KEY"),
        sport_key=current_app.config.get("ODDS_API_SPORT_KEY", "mma_mixed_martial_arts"),
        regions=current_app.config.get("ODDS_API_REGIONS", "us"),
        markets=current_app.config.get("ODDS_API_MARKETS", "h2h"),
        timeout=current_app.config.get("ODDS_API_TIMEOUT_SECONDS", 10.0),
    )


def _quota_message(quota: QuotaInfo | None) -> str | None:
    if quota is None:
        return None
    message = quota.as_message()
    return f"Quota: {message}" if message else None


@web.route("/events/<int:event_id>/provider-bouts", methods=["GET", "POST"])
def provider_bouts(event_id: int):
    database_path = current_app.config["DATABASE_PATH"]
    event = get_event(database_path, event_id)
    if event is None:
        return "Event not found", 404
    if event["status"] in {"completed", "canceled"}:
        flash("Completed or canceled cards cannot import provider bouts.", "error")
        return redirect(url_for("web.event_detail", event_id=event_id))
    provider = _odds_provider()
    try:
        if request.method == "POST":
            selected_ids = request.form.getlist("provider_event_id")
            imported = import_selected_bouts(
                database_path,
                event_id,
                provider,
                selected_ids,
            )
            message = f"Imported {len(imported.fight_ids)} selected bout(s)."
            if _quota_message(imported.quota):
                message += f" {_quota_message(imported.quota)}."
            flash(message, "success")
            return redirect(url_for("web.event_detail", event_id=event_id))
        bouts = provider.discover_events()
        return render_template(
            "provider_bouts.html",
            event=event,
            bouts=bouts,
            quota=_quota_message(provider.last_quota),
        )
    except (OddsProviderError, OddsImportError, ValidationError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("web.event_detail", event_id=event_id))


@web.post("/events/<int:event_id>/odds/refresh")
def refresh_odds(event_id: int):
    try:
        provider = _odds_provider()
        imported = refresh_odds_for_card(
            current_app.config["DATABASE_PATH"],
            event_id,
            provider,
        )
        message = f"Imported {imported.snapshot_count} odds snapshot(s)."
        if _quota_message(imported.quota):
            message += f" {_quota_message(imported.quota)}."
        flash(message, "success")
    except (OddsProviderError, OddsImportError, ValidationError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.event_detail", event_id=event_id))


@web.get("/analytics")
def analytics():
    return render_template(
        "analytics.html",
        metrics=dashboard_metrics(current_app.config["DATABASE_PATH"]),
    )


def _form_rows(event: dict | None) -> list[dict]:
    rows = list(event["fights"]) if event else []
    rows.extend({} for _ in range(max(0, 15 - len(rows))))
    return rows[:15]


def _render_event_form(event: dict | None = None, *, edit: bool = False):
    settings = get_tracker_settings(current_app.config["DATABASE_PATH"])
    return render_template(
        "event_form.html",
        event=event,
        edit=edit,
        rows=_form_rows(event),
        analysts=get_analysts(current_app.config["DATABASE_PATH"]),
        default_stake=f"{settings['default_stake_cents'] / 100:.2f}",
    )


@web.route("/events/new", methods=["GET", "POST"])
def new_event():
    if request.method == "POST":
        try:
            fights = parse_fights(
                request.form,
                current_app.config["DATABASE_PATH"],
                allow_empty=True,
            )
            event_id = save_event(
                current_app.config["DATABASE_PATH"],
                promotion=request.form.get("promotion", "UFC"),
                name=request.form.get("name", ""),
                event_date=request.form.get("event_date", ""),
                fights=fights,
                allow_empty=True,
            )
            flash("Card saved.", "success")
            return redirect(url_for("web.event_detail", event_id=event_id))
        except ValidationError as exc:
            flash(str(exc), "error")
    return _render_event_form()


@web.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def edit_event(event_id: int):
    database_path = current_app.config["DATABASE_PATH"]
    event = get_event(database_path, event_id)
    if event is None:
        return "Event not found", 404
    if request.method == "POST":
        try:
            fights = parse_fights(request.form, database_path)
            save_event(
                database_path,
                event_id=event_id,
                promotion=request.form.get("promotion", "UFC"),
                name=request.form.get("name", ""),
                event_date=request.form.get("event_date", ""),
                fights=fights,
            )
            flash("Card updated.", "success")
            return redirect(url_for("web.event_detail", event_id=event_id))
        except ValidationError as exc:
            flash(str(exc), "error")
    return _render_event_form(event, edit=True)


@web.get("/events/<int:event_id>")
def event_detail(event_id: int):
    event = get_event(current_app.config["DATABASE_PATH"], event_id)
    if event is None:
        return "Event not found", 404
    return render_template("event_detail.html", event=event)


@web.post("/events/<int:event_id>/settle")
def settle(event_id: int):
    try:
        results = {
            int(key.removeprefix("winner_")): value
            for key, value in request.form.items()
            if key.startswith("winner_")
        }
        settle_event(current_app.config["DATABASE_PATH"], event_id, results)
        flash("Card settled.", "success")
    except (ValidationError, ValueError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("web.event_detail", event_id=event_id))
