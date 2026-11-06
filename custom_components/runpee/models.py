"""Validated, spoiler-minimized provider models (no Home Assistant dependency)."""

from dataclasses import asdict, dataclass
from typing import Any


class InvalidData(ValueError):
    """The provider returned an unsupported response."""


def integer(value: Any, minimum: int = 0, maximum: int = 86400) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise InvalidData("Invalid integer")
    return int(value)


def text(value: Any, maximum: int = 2048) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise InvalidData("Invalid text")
    return value


@dataclass(frozen=True)
class Break:
    pee_id: int
    offset_seconds: int
    duration_seconds: int
    cue: str
    recommended: bool


@dataclass(frozen=True)
class Movie:
    movie_id: int
    title: str
    run_time: int
    timer_cue: str
    peetimes: tuple[Break, ...]
    credits_length: int | None
    has_extras: bool | None

    def response(self) -> dict[str, Any]:
        result = asdict(self)
        result["peetimes"] = [asdict(item) for item in self.peetimes]
        return result


def parse_movie(data: Any, movie_id: int) -> Movie:
    try:
        if (
            not isinstance(data, dict)
            or integer(data["movie_id"], 1, 2**31 - 1) != movie_id
        ):
            raise InvalidData("Invalid movie")
        items = data["peetimes"]
        if not isinstance(items, list) or len(items) > 100:
            raise InvalidData("Invalid breaks")
        breaks = []
        for item in items:
            # Content alerts are not safe bathroom breaks. Fail closed if malformed.
            is_alert = item.get("is_alert", False)
            if not isinstance(is_alert, bool):
                raise InvalidData("Invalid alert flag")
            if is_alert:
                continue
            recommended = item.get("is_recommended", False)
            if not isinstance(recommended, bool):
                raise InvalidData("Invalid recommendation")
            breaks.append(
                Break(
                    integer(item["pee_id"], 1, 2**31 - 1),
                    integer(item["pt_start"]),
                    integer(item["len"], 1),
                    text(item["cue"]),
                    recommended,
                )
            )
        extras = data.get("has_extras")
        if extras is not None and not isinstance(extras, bool):
            raise InvalidData("Invalid extras")
        return Movie(
            movie_id,
            text(data["title"], 255),
            integer(data["run_time"], 1, 1440),
            text(data.get("timer_cue", "")),
            tuple(sorted(breaks, key=lambda item: item.offset_seconds)),
            integer(data["credits_length"])
            if data.get("credits_length") is not None
            else None,
            extras,
        )
    except KeyError, TypeError, AttributeError:
        raise InvalidData("Invalid movie response") from None


def search_release(item: dict[str, Any]) -> dict[str, Any]:
    """Keep original release year, never substitute regional/effective dates."""
    value = item.get("release_date")
    if value in (None, ""):
        return {}
    from datetime import date

    try:
        release = date.fromisoformat(text(value, 10))
    except ValueError:
        raise InvalidData("Invalid release date") from None
    return {"release_date": value, "year": release.year}


def parse_search(data: Any) -> list[dict[str, Any]]:
    try:
        movies = data["movies"]
        if not isinstance(movies, list) or len(movies) > 500:
            raise InvalidData("Invalid search")
        return [
            {
                "movie_id": integer(item["movie_id"], 1, 2**31 - 1),
                "title": text(item["title"], 255),
                "run_time": integer(item["run_time"], 1, 1440),
                **search_release(item),
            }
            for item in movies
        ]
    except KeyError, TypeError:
        raise InvalidData("Invalid search response") from None
