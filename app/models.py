"""Provider-neutral values passed between adapters and the UI."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Artist:
    id: str
    name: str
    raw: Any = None


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist_name: str
    uri: str | None = None
    popularity: int | None = None
    raw: Any = None
    release_date: str | None = None
    release_type: str | None = None


@dataclass(frozen=True)
class PlaylistResult:
    name: str
    url: str | None
    track_count: int
