from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence

import httpx

from .base import (
    BookmakerOdds,
    OddsEvent,
    OddsOutcome,
    OddsProviderAuthenticationError,
    OddsProviderError,
    OddsProviderNotFound,
    OddsProviderQuotaExceeded,
    OddsProviderResponseError,
    OddsProviderUnavailable,
    QuotaInfo,
)


@dataclass(frozen=True)
class HTTPResponse:
    status_code: int
    headers: Mapping[str, str]
    payload: object

    def json(self) -> object:
        return self.payload


HTTPGet = Callable[[str, Mapping[str, str], float], HTTPResponse]


def _default_http_get(
    url: str,
    params: Mapping[str, str],
    timeout: float,
) -> HTTPResponse:
    try:
        response = httpx.get(
            url,
            params=dict(params),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
    except httpx.TimeoutException as exc:
        raise OddsProviderUnavailable("The Odds API request timed out") from exc
    except httpx.HTTPError as exc:
        raise OddsProviderUnavailable("The Odds API could not be reached") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return HTTPResponse(
        status_code=response.status_code,
        headers=dict(response.headers),
        payload=payload,
    )


def normalize_timestamp(value: object) -> str:
    if isinstance(value, (int, float)):
        timestamp = datetime.fromtimestamp(value, tz=UTC)
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OddsProviderResponseError("provider timestamp is not ISO-8601") from exc
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        timestamp = timestamp.astimezone(UTC)
    else:
        raise OddsProviderResponseError("provider response is missing a timestamp")
    return timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OddsProviderResponseError(f"provider response is missing {field_name}")
    return value.strip()


def _american_price(value: object) -> int:
    try:
        price = int(value)
    except (TypeError, ValueError) as exc:
        raise OddsProviderResponseError("provider outcome has an invalid moneyline") from exc
    if price == 0 or -100 < price < 100:
        raise OddsProviderResponseError("provider outcome has an invalid moneyline")
    return price


def _normalize_bookmakers(payload: Mapping[str, Any]) -> tuple[BookmakerOdds, ...]:
    raw_bookmakers = payload.get("bookmakers", [])
    if raw_bookmakers is None:
        return ()
    if not isinstance(raw_bookmakers, list):
        raise OddsProviderResponseError("provider bookmakers must be a list")

    bookmakers: list[BookmakerOdds] = []
    for raw_bookmaker in raw_bookmakers:
        if not isinstance(raw_bookmaker, Mapping):
            continue
        if not isinstance(raw_bookmaker.get("key"), str) or not isinstance(
            raw_bookmaker.get("title"), str
        ):
            continue
        key = raw_bookmaker["key"].strip()
        title = raw_bookmaker["title"].strip()
        if not key or not title:
            continue
        markets = raw_bookmaker.get("markets", [])
        if not isinstance(markets, list):
            continue
        h2h_market = next(
            (
                market
                for market in markets
                if isinstance(market, Mapping) and market.get("key") == "h2h"
            ),
            None,
        )
        if h2h_market is None or not isinstance(h2h_market.get("outcomes"), list):
            continue
        outcomes: list[OddsOutcome] = []
        for raw_outcome in h2h_market["outcomes"]:
            if not isinstance(raw_outcome, Mapping):
                continue
            try:
                outcomes.append(
                    OddsOutcome(
                        fighter=_required_text(raw_outcome.get("name"), "outcome name"),
                        moneyline=_american_price(raw_outcome.get("price")),
                    )
                )
            except OddsProviderResponseError:
                continue
        if outcomes:
            last_update = raw_bookmaker.get("last_update")
            if last_update is None:
                last_update = h2h_market.get("last_update")
            normalized_last_update = None
            if last_update:
                try:
                    normalized_last_update = normalize_timestamp(last_update)
                except OddsProviderResponseError:
                    normalized_last_update = None
            bookmakers.append(
                BookmakerOdds(
                    key=key,
                    title=title,
                    last_update=normalized_last_update,
                    outcomes=tuple(outcomes),
                )
            )
    return tuple(bookmakers)


def normalize_event(payload: Mapping[str, Any], default_sport_key: str = "") -> OddsEvent:
    if not isinstance(payload, Mapping):
        raise OddsProviderResponseError("provider event must be an object")
    return OddsEvent(
        provider_event_id=_required_text(payload.get("id"), "event id"),
        sport_key=_required_text(payload.get("sport_key") or default_sport_key, "sport key"),
        sport_title=_required_text(
            payload.get("sport_title") or payload.get("sport_key"), "sport title"
        ),
        commence_time=normalize_timestamp(payload.get("commence_time")),
        home_team=_required_text(payload.get("home_team"), "home team"),
        away_team=_required_text(payload.get("away_team"), "away team"),
        bookmakers=_normalize_bookmakers(payload),
    )


def normalize_events(payload: object, default_sport_key: str = "") -> list[OddsEvent]:
    if not isinstance(payload, list):
        raise OddsProviderResponseError("provider event response must be a list")
    return [normalize_event(event, default_sport_key) for event in payload]


def _event_ids(event_ids: Sequence[str]) -> str:
    unique = list(dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip()))
    return ",".join(unique)


class TheOddsAPIProvider:
    """The Odds API v4 adapter with an injectable httpx-compatible boundary."""

    provider_name = "the_odds_api"

    def __init__(
        self,
        api_key: str | None,
        *,
        sport_key: str = "mma_mixed_martial_arts",
        regions: str = "us",
        markets: str = "h2h",
        base_url: str = "https://api.the-odds-api.com",
        timeout: float = 10.0,
        http_get: HTTPGet | None = None,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.sport_key = sport_key
        self.regions = regions
        self.markets = markets
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_get = http_get or _default_http_get
        self.last_quota: QuotaInfo | None = None

    def _request(self, path: str, params: Mapping[str, str]) -> object:
        if not self.api_key:
            raise OddsProviderAuthenticationError("ODDS_API_KEY is not configured")
        request_params = {
            "apiKey": self.api_key,
            "dateFormat": "iso",
            **params,
        }
        try:
            response = self._http_get(
                f"{self.base_url}{path}", request_params, self.timeout
            )
        except OddsProviderError:
            raise
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise OddsProviderUnavailable("The Odds API request timed out") from exc
        except Exception as exc:
            raise OddsProviderUnavailable("The Odds API request failed") from exc

        self.last_quota = QuotaInfo.from_headers(dict(response.headers))
        payload = response.json()
        error_code = payload.get("error_code") if isinstance(payload, Mapping) else None
        message = payload.get("message") if isinstance(payload, Mapping) else None
        error_kwargs = {
            "status_code": response.status_code,
            "error_code": str(error_code) if error_code else None,
            "headers": dict(response.headers),
            "quota": self.last_quota,
        }
        if response.status_code >= 400 or error_code:
            error_message = str(message or error_code or "The Odds API request failed")
            if response.status_code == 429 or error_code in {
                "EXCEEDED_FREQ_LIMIT",
                "OUT_OF_USAGE_CREDITS",
            }:
                raise OddsProviderQuotaExceeded(error_message, **error_kwargs)
            if response.status_code in {401, 403} or error_code in {
                "MISSING_KEY",
                "INVALID_KEY",
                "DEACTIVATED_KEY",
            }:
                raise OddsProviderAuthenticationError(error_message, **error_kwargs)
            if response.status_code == 404 or error_code == "EVENT_NOT_FOUND":
                raise OddsProviderNotFound(error_message, **error_kwargs)
            if response.status_code >= 500:
                raise OddsProviderUnavailable(error_message, **error_kwargs)
            raise OddsProviderResponseError(error_message, **error_kwargs)
        return payload

    def discover_events(self, event_ids: Sequence[str] | None = None) -> list[OddsEvent]:
        params: dict[str, str] = {}
        if event_ids:
            params["eventIds"] = _event_ids(event_ids)
        payload = self._request(f"/v4/sports/{self.sport_key}/events", params)
        return normalize_events(payload, self.sport_key)

    def fetch_odds(self, event_ids: Sequence[str]) -> list[OddsEvent]:
        selected = _event_ids(event_ids)
        if not selected:
            return []
        payload = self._request(
            f"/v4/sports/{self.sport_key}/odds",
            {
                "eventIds": selected,
                "regions": self.regions,
                "markets": self.markets,
                "oddsFormat": "american",
            },
        )
        return normalize_events(payload, self.sport_key)
