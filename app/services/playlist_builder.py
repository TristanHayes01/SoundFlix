"""Thread-safe orchestration; adapters stay unaware of UI widgets."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
import re
from app.adapters.base import BaseMusicAdapter
from app.models import PlaylistResult, Track

Log = Callable[[str], None]


@dataclass(frozen=True)
class PlaylistOptions:
    songs_per_artist: int = 5
    track_source: str = "popular"  # "popular" or "recent"
    skip_remixes: bool = False
    singles_only: bool = False
    released_within_days: int = 0  # 0 means all available dates.
    dedupe_titles: bool = True


@dataclass
class PreviewArtist:
    requested_name: str
    matched_name: str | None = None
    tracks: list[Track] = field(default_factory=list)
    note: str | None = None


@dataclass
class PlaylistPreview:
    artists: list[PreviewArtist] = field(default_factory=list)

    @property
    def tracks(self) -> list[Track]:
        return [track for artist in self.artists for track in artist.tracks]


class PlaylistBuilder:
    def __init__(self, adapter: BaseMusicAdapter, log: Log):
        self.adapter, self.log = adapter, log

    def collect(self, artists: list[str], options: PlaylistOptions) -> PlaylistPreview:
        preview = PlaylistPreview()
        seen_track_ids: set[str] = set()
        seen_titles: set[str] = set()
        for index, artist_name in enumerate(artists, start=1):
            self.log(f"[{index}/{len(artists)}] Searching: {artist_name}")
            artist = self.adapter.search_artist(artist_name)
            if not artist:
                self.log(f"  Not found: {artist_name}")
                preview.artists.append(PreviewArtist(artist_name, note="No matching artist found"))
                continue
            tracks = (self.adapter.get_recent_tracks(artist, options.songs_per_artist)
                      if options.track_source == "recent"
                      else self.adapter.get_top_5_tracks(artist, options.songs_per_artist))
            tracks = self._filter(tracks, options, seen_titles)
            if len(tracks) < options.songs_per_artist:
                self.log(f"  Only {len(tracks)} of {options.songs_per_artist} tracks available for {artist.name} after filters.")
            accepted: list[Track] = []
            for track in tracks:
                if track.id not in seen_track_ids:
                    accepted.append(track)
                    seen_track_ids.add(track.id)
            preview.artists.append(PreviewArtist(artist_name, artist.name, accepted))
            self.log(f"  Found {len(accepted)} tracks from {artist.name}.")
        if not preview.tracks:
            raise RuntimeError("No playable tracks were found. Check artist names and platform availability.")
        return preview

    def create(self, playlist_name: str, tracks: list[Track], description: str = "",
               artwork: bytes | None = None) -> PlaylistResult:
        if not tracks:
            raise RuntimeError("Select at least one track before creating the playlist.")
        self.log(f"Creating playlist with {len(tracks)} approved tracks…")
        return self.adapter.create_playlist(playlist_name, tracks, description, artwork)

    def build(self, artists: list[str], playlist_name: str, songs_per_artist: int = 5,
              track_source: str = "popular") -> PlaylistResult:
        """Compatibility convenience method for non-interactive callers."""
        preview = self.collect(artists, PlaylistOptions(songs_per_artist, track_source))
        return self.create(playlist_name, preview.tracks)

    def _filter(self, tracks: list[Track], options: PlaylistOptions, seen_titles: set[str]) -> list[Track]:
        cutoff = date.today() - timedelta(days=options.released_within_days) if options.released_within_days else None
        output: list[Track] = []
        for track in tracks:
            title_key = re.sub(r"\s*\([^)]*\)|\s*\[[^]]*\]", "", track.title).casefold().strip()
            if options.skip_remixes and re.search(r"\b(remix|mix|vip|edit)\b", track.title, re.IGNORECASE):
                continue
            if options.singles_only and track.release_type not in (None, "single"):
                continue
            if cutoff and track.release_date:
                try:
                    if date.fromisoformat(track.release_date[:10]) < cutoff:
                        continue
                except ValueError:
                    pass  # Unknown precision: retain instead of silently discarding it.
            if options.dedupe_titles and title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            output.append(track)
        return output
