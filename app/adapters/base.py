"""Platform adapter contract. The rest of the program only depends on this."""
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Callable
from app.models import Artist, PlaylistResult, Track


class BaseMusicAdapter(ABC):
    name: str

    @abstractmethod
    def authenticate(self, log: Callable[[str], None]) -> None: ...

    @abstractmethod
    def search_artist(self, query: str) -> Artist | None: ...

    @abstractmethod
    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]: ...

    @abstractmethod
    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        """Return the newest distinct catalog tracks for an artist, newest first."""

    @abstractmethod
    def create_playlist(self, name: str, tracks: list[Track]) -> PlaylistResult: ...
