from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from .services.public_api import (
    PublicApiError,
    get_public_analyst,
    get_public_event,
    list_public_analysts,
    list_public_events,
    load_public_picks,
    parse_pagination,
    parse_pick_filters,
    public_pick,
    public_stats,
)


api_v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")


@api_v1.get("")
def api_status():
    return _success({"status": "ok"})


@api_v1.errorhandler(PublicApiError)
def handle_public_api_error(error: PublicApiError):
    return jsonify({"error": {"code": error.code, "message": error.message}}), error.status_code


def _success(data, **meta):
    return jsonify({"data": data, "meta": {"version": "v1", **meta}})


def _paginated(data: list, limit: int, offset: int):
    total = len(data)
    return _success(
        data[offset : offset + limit],
        limit=limit,
        offset=offset,
        count=min(limit, max(0, total - offset)),
        total=total,
        has_more=offset + limit < total,
    )


def _event_id(value: str) -> int:
    try:
        event_id = int(value)
    except ValueError as exc:
        raise PublicApiError("invalid_event_id", "event_id must be an integer") from exc
    if event_id <= 0:
        raise PublicApiError("invalid_event_id", "event_id must be positive")
    return event_id


def _database_path():
    return current_app.config["DATABASE_PATH"]


@api_v1.get("/analysts")
def analysts():
    limit, offset = parse_pagination(request.args)
    return _paginated(list_public_analysts(_database_path()), limit, offset)


@api_v1.get("/analysts/<slug>")
def analyst(slug: str):
    result = get_public_analyst(_database_path(), slug)
    if result is None:
        raise PublicApiError("analyst_not_found", "analyst not found", 404)
    return _success(result)


@api_v1.get("/analysts/<slug>/picks")
def analyst_picks(slug: str):
    if get_public_analyst(_database_path(), slug) is None:
        raise PublicApiError("analyst_not_found", "analyst not found", 404)
    filters = parse_pick_filters(request.args)
    limit, offset = parse_pagination(request.args)
    picks = [
        public_pick(row)
        for row in load_public_picks(
            _database_path(), filters, analyst_slug=slug
        )
    ]
    return _paginated(picks, limit, offset)


@api_v1.get("/analysts/<slug>/stats")
def analyst_stats(slug: str):
    if get_public_analyst(_database_path(), slug) is None:
        raise PublicApiError("analyst_not_found", "analyst not found", 404)
    filters = parse_pick_filters(request.args)
    return _success(public_stats(_database_path(), slug, filters))


@api_v1.get("/events")
def events():
    filters = parse_pick_filters(request.args)
    limit, offset = parse_pagination(request.args)
    return _paginated(list_public_events(_database_path(), filters), limit, offset)


@api_v1.get("/events/<event_id>")
def event(event_id: str):
    result = get_public_event(_database_path(), _event_id(event_id))
    if result is None:
        raise PublicApiError("event_not_found", "event not found", 404)
    return _success(result)


@api_v1.get("/events/<event_id>/picks")
def event_picks(event_id: str):
    parsed_event_id = _event_id(event_id)
    if get_public_event(_database_path(), parsed_event_id) is None:
        raise PublicApiError("event_not_found", "event not found", 404)
    filters = parse_pick_filters(request.args)
    limit, offset = parse_pagination(request.args)
    picks = [
        public_pick(row)
        for row in load_public_picks(
            _database_path(), filters, event_id=parsed_event_id
        )
    ]
    return _paginated(picks, limit, offset)
