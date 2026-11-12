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

    def search_artists(self, query: str, limit: int = 10) -> list[Artist]:
        """Return candidate artists in provider relevance order.

        Adapters override this when their catalog exposes several candidates.
        The fallback keeps third-party adapters compatible with SoundFlix.
        """
        artist = self.search_artist(query)
        return [artist] if artist else []

    def artist_from_profile_url(self, url: str) -> Artist | None:
        """Resolve a provider profile URL to a playable artist candidate."""
        raise RuntimeError(f"Pasted profile links are not supported for {self.name}.")

    @abstractmethod
    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]: ...

    @abstractmethod
    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        """Return the newest distinct catalog tracks for an artist, newest first."""

    @abstractmethod
    def create_playlist(self, name: str, tracks: list[Track], description: str = "") -> PlaylistResult: ...
