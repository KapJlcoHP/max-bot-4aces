"""Пользовательская локация и её внутреннее представление времени."""

import json
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parents[1] / "content"


def load_cities() -> list[dict]:
    return json.loads((CONTENT_DIR / "cities.json").read_text(encoding="utf-8"))["cities"]


def city_for_location(city: str | None, region: str | None) -> dict | None:
    if not city or not region:
        return None
    return next((item for item in load_cities() if item["title"] == city and item["region"] == region), None)


def cities_for_region(region: str | None) -> list[dict]:
    return [item for item in load_cities() if not region or item["region"] == region]


def legacy_city_candidates(tz: str | None, region: str | None = None) -> list[dict]:
    """Return directory matches; callers must not guess when there are several."""
    return [item for item in load_cities() if item["tz"] == (tz or "") and (not region or item["region"] == region)]


def timezone_for_city(city: str | None, region: str | None, fallback: str = "Europe/Moscow") -> str:
    item = city_for_location(city, region)
    return item["tz"] if item else fallback
