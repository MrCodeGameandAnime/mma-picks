from __future__ import annotations

from collections.abc import Mapping


CATALOG_PROVIDER = "ufcstats"


class CatalogReadOnlyError(ValueError):
    """Raised when tracker mutation code targets authoritative catalog data."""


def is_catalog_event(event: Mapping[str, object] | None) -> bool:
    return event is not None and event["external_provider"] == CATALOG_PROVIDER


def reject_catalog_event(event: Mapping[str, object] | None) -> None:
    if event is None:
        raise CatalogReadOnlyError("event not found")
    if is_catalog_event(event):
        raise CatalogReadOnlyError("UFCStats catalog events are read-only")
