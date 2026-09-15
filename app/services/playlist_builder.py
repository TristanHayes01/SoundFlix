"""Thread-safe orchestration; adapters stay unaware of UI widgets."""
from __future__ import annotations
from collections.abc import Callable
from app.adapters.base import BaseMusicAdapter
from app.models import PlaylistResult, Track

Log = Callable[[str], None]


class PlaylistBuilder:
    def __init__(self, adapter: BaseMusicAdapter, log: Log):
        self.adapter, self.log = adapter, log

    def build(self, artists: list[str], playlist_name: str, songs_per_artist: int = 5,
              track_source: str = "popular") -> PlaylistResult:
        selected: list[Track] = []
        seen_track_ids: set[str] = set()
        for index, artist_name in enumerate(artists, start=1):
            self.log(f"[{index}/{len(artists)}] Searching: {artist_name}")
            artist = self.adapter.search_artist(artist_name)
            if not artist:
                self.log(f"  Not found: {artist_name}")
                continue
            tracks = (self.adapter.get_recent_tracks(artist, songs_per_artist)
                      if track_source == "recent"
                      else self.adapter.get_top_5_tracks(artist, songs_per_artist))
            if len(tracks) < songs_per_artist:
                self.log(f"  Only {len(tracks)} of {songs_per_artist} playable tracks available for {artist.name}.")
            for track in tracks:
                if track.id not in seen_track_ids:
                    selected.append(track)
                    seen_track_ids.add(track.id)
            self.log(f"  Added {len(tracks)} tracks from {artist.name}.")
        if not selected:
            raise RuntimeError("No playable tracks were found. Check artist names and platform availability.")
        self.log(f"Creating playlist with {len(selected)} unique tracks…")
        return self.adapter.create_playlist(playlist_name, selected)
