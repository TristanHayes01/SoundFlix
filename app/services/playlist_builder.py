"""Thread-safe orchestration; adapters stay unaware of UI widgets."""
from __future__ import annotations
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
import re
import threading
from app.adapters.base import BaseMusicAdapter
from app.models import Artist, PlaylistResult, Track

Log = Callable[[str], None]


@dataclass(frozen=True)
class PlaylistOptions:
    include_popular: bool = True
    popular_song_count: int = 5
    include_recent: bool = False
    recent_song_count: int = 5
    skip_remixes: bool = False
    singles_only: bool = False
    released_within_days: int = 0  # 0 means all available dates.
    release_start: date | None = None
    release_end: date | None = None
    dedupe_titles: bool = True
    include_liked_tracks: bool = False
    include_playlist_tracks: bool = False
    selected_playlist_ids: tuple[str, ...] = ()
    all_library_playlists: bool = False
    include_collaborations: bool = True

    @property
    def requested_count(self) -> int:
        return (self.popular_song_count if self.include_popular else 0) + (self.recent_song_count if self.include_recent else 0)

    @property
    def has_release_filter(self) -> bool:
        return bool(self.released_within_days or self.release_start or self.release_end)


@dataclass(frozen=True)
class ArtistCandidate:
    artist: Artist
    sample_tracks: list[Track]
    collaborators: list[str]


@dataclass(frozen=True)
class AmbiguousArtist:
    requested_name: str
    candidates: list[ArtistCandidate]


@dataclass
class PreviewArtist:
    requested_name: str
    matched_name: str | None = None
    tracks: list[Track] = field(default_factory=list)
    note: str | None = None
    profile_image_url: str | None = None


@dataclass
class PlaylistPreview:
    artists: list[PreviewArtist] = field(default_factory=list)

    @property
    def tracks(self) -> list[Track]:
        return [track for artist in self.artists for track in artist.tracks]


class PlaylistBuilder:
    def __init__(self, adapter: BaseMusicAdapter, log: Log,
                 adapter_factory: Callable[[], BaseMusicAdapter] | None = None,
                 worker_count: int = 1,
                 progress: Callable[[str, int, int, int], None] | None = None):
        self.adapter, self.log = adapter, log
        self.adapter_factory = adapter_factory
        self.worker_count = max(1, worker_count)
        self.progress = progress

    def _report_progress(self, phase: str, completed: int, total: int,
                         active_workers: int = 0) -> None:
        if self.progress:
            self.progress(phase, completed, total, active_workers)

    def _worker_adapter(self) -> BaseMusicAdapter:
        if not self.adapter_factory:
            return self.adapter
        adapter = self.adapter_factory()
        adapter.authenticate(lambda _message: None)
        return adapter

    def find_ambiguous_artists(self, artists: list[str],
                               on_ambiguous: Callable[[AmbiguousArtist], None] | None = None
                               ) -> tuple[list[AmbiguousArtist], dict[str, Artist | None]]:
        """Find playable same-name matches and prepare five-song previews.

        Candidates with no playable sample songs are not shown. A single
        remaining playable candidate is selected automatically. The optional
        callback streams each unresolved match without pausing the scan.
        """
        ambiguous: list[AmbiguousArtist] = []
        resolved: dict[str, Artist | None] = {}
        handled: set[str] = set()
        names: list[str] = []
        for artist_name in artists:
            key = artist_name.casefold()
            if key in handled:
                continue
            handled.add(key)
            names.append(artist_name)
        self._report_progress("Searching", 0, len(names), 0)

        def discover(artist_name: str) -> tuple[str, AmbiguousArtist | None, Artist | None, bool]:
            adapter = self._worker_adapter()
            key = artist_name.casefold()
            matches = [candidate for candidate in adapter.search_artists(artist_name)
                       if candidate.name.casefold() == key]
            unique = {candidate.id: candidate for candidate in matches}
            if len(unique) < 2:
                return key, None, None, False
            self.log(f"Multiple {artist_name} profiles found. Preparing song previews for confirmation…")
            def preview_candidate(candidate: Artist) -> ArtistCandidate | None:
                try:
                    candidate_adapter = self._worker_adapter()
                    active_candidate = candidate
                    if self.adapter_factory and candidate.profile_url:
                        active_candidate = candidate_adapter.artist_from_profile_url(candidate.profile_url) or candidate
                    return self.candidate_preview(active_candidate, candidate_adapter)
                except Exception as error:
                    self.log(f"  Could not load sample songs for {candidate.name}: {error}")
                    return None

            candidates: list[ArtistCandidate] = []
            source_candidates = list(unique.values())
            if self.worker_count > 1 and self.adapter_factory:
                with ThreadPoolExecutor(max_workers=min(self.worker_count, len(source_candidates)), thread_name_prefix="soundflix-profiles") as executor:
                    previews = list(executor.map(preview_candidate, source_candidates))
            else:
                previews = [preview_candidate(candidate) for candidate in source_candidates]
            for candidate, preview in zip(source_candidates, previews):
                if preview:
                    candidates.append(preview)
                else:
                    self.log(f"  Skipping {candidate.name}: no playable sample songs found.")
            if not candidates:
                self.log(f"  Skipping {artist_name}: none of the same-name profiles have playable songs.")
                return key, None, None, True
            elif len(candidates) == 1:
                self.log(f"  Using the only playable {artist_name} profile.")
                return key, None, candidates[0].artist, True
            else:
                return key, AmbiguousArtist(artist_name, candidates), None, True

        def record(result: tuple[str, AmbiguousArtist | None, Artist | None, bool]) -> None:
            key, match, automatic, handled_match = result
            if not handled_match:
                return
            if match:
                ambiguous.append(match)
                if on_ambiguous:
                    on_ambiguous(match)
            else:
                resolved[key] = automatic
        progress_lock = threading.Lock()
        completed = 0
        active_workers = 0

        def tracked_discover(name: str) -> tuple[str, AmbiguousArtist | None, Artist | None, bool]:
            nonlocal completed, active_workers
            with progress_lock:
                active_workers += 1
                active = active_workers
                done = completed
            self._report_progress("Searching", done, len(names), active)
            try:
                return discover(name)
            finally:
                with progress_lock:
                    active_workers -= 1
                    completed += 1
                    active = active_workers
                    done = completed
                self._report_progress("Searching", done, len(names), active)

        if self.worker_count > 1 and self.adapter_factory:
            with ThreadPoolExecutor(max_workers=self.worker_count, thread_name_prefix="soundflix-search") as executor:
                futures = [executor.submit(tracked_discover, name) for name in names]
                for future in as_completed(futures):
                    record(future.result())
        else:
            for name in names:
                record(tracked_discover(name))
        return ambiguous, resolved

    def candidate_preview(self, artist: Artist, adapter: BaseMusicAdapter | None = None) -> ArtistCandidate | None:
        """Build a five-song preview plus broad-catalog collaborator cues."""
        adapter = adapter or self.adapter
        samples = adapter.get_top_5_tracks(artist, 5)
        if not samples:
            return None
        catalog_tracks = list(samples)
        # Recent catalog tracks complement the provider's popularity ranking and
        # expose collaborations not represented in the top-five preview.
        try:
            catalog_tracks.extend(adapter.get_recent_tracks(artist, 100))
        except Exception as error:
            self.log(f"  Could not load extended collaborator credits for {artist.name}: {error}")
        return ArtistCandidate(artist, samples, self._sample_collaborators(artist, catalog_tracks, limit=10))

    @staticmethod
    def _sample_collaborators(artist: Artist, tracks: list[Track], limit: int = 10) -> list[str]:
        """Extract credited collaborators from a broad set of artist tracks."""
        collaborators: list[str] = []
        seen: set[str] = {artist.name.casefold()}

        def add(value: str | None) -> None:
            if not value:
                return
            name = value.strip()
            key = name.casefold()
            if name and key not in seen:
                seen.add(key)
                collaborators.append(name)

        for track in tracks:
            raw_artists = track.raw.get("artists", []) if isinstance(track.raw, dict) else getattr(track.raw, "artists", [])
            for credited in raw_artists or []:
                add(credited.get("name") if isinstance(credited, dict) else getattr(credited, "name", None))
            for name in re.split(r"\s*(?:,|&|\b(?:feat\.?|ft\.?)\b)\s*", track.artist_name, flags=re.IGNORECASE):
                add(name)
            featured = re.search(r"\b(?:feat\.?|ft\.?)\s+([^\]\)]+)", track.title, re.IGNORECASE)
            if featured:
                for name in re.split(r"\s*(?:,|&)\s*", featured.group(1)):
                    add(name)
        return collaborators[:limit]

    def collect(self, artists: list[str], options: PlaylistOptions,
                selected_artists: dict[str, Artist | None] | None = None) -> PlaylistPreview:
        preview = PlaylistPreview()
        seen_track_ids: set[str] = set()
        seen_titles: set[str] = set()
        selections = selected_artists or {}
        self._report_progress("Collecting tracks", 0, len(artists), 0)

        def lookup(index: int, artist_name: str) -> tuple[int, Artist | None, list[Track], str | None]:
            self.log(f"[{index}/{len(artists)}] Searching: {artist_name}")
            adapter = self._worker_adapter()
            key = artist_name.casefold()
            artist = selections[key] if key in selections else adapter.search_artist(artist_name)
            if not artist:
                note = "Skipped by you" if key in selections else "No matching artist found"
                return index, None, [], note
            # A selected TIDAL artist belongs to the discovery session. Resolve
            # it again in this worker's independent session before querying tracks.
            if key in selections and self.adapter_factory and artist.profile_url:
                artist = adapter.artist_from_profile_url(artist.profile_url) or artist
            tracks: list[Track] = []
            if options.include_popular:
                # Fetch a larger popularity pool first when a release window is
                # active. Otherwise five older hits can be filtered away before
                # SoundFlix has a chance to discover eligible newer songs.
                popular_limit = max(options.popular_song_count, 50) if options.has_release_filter else options.popular_song_count
                tracks.extend(replace(track, selection_source="popular") for track in adapter.get_top_5_tracks(artist, popular_limit))
            if options.include_recent:
                tracks.extend(replace(track, selection_source="recent") for track in adapter.get_recent_tracks(artist, options.recent_song_count))
            return index, artist, tracks, None

        progress_lock = threading.Lock()
        completed = 0
        active_workers = 0

        def tracked_lookup(index: int, artist_name: str) -> tuple[int, Artist | None, list[Track], str | None]:
            nonlocal completed, active_workers
            with progress_lock:
                active_workers += 1
                active = active_workers
                done = completed
            self._report_progress("Collecting tracks", done, len(artists), active)
            try:
                return lookup(index, artist_name)
            finally:
                with progress_lock:
                    active_workers -= 1
                    completed += 1
                    active = active_workers
                    done = completed
                self._report_progress("Collecting tracks", done, len(artists), active)

        if self.worker_count > 1 and self.adapter_factory:
            with ThreadPoolExecutor(max_workers=self.worker_count, thread_name_prefix="soundflix-tracks") as executor:
                futures = [executor.submit(tracked_lookup, index, name) for index, name in enumerate(artists, start=1)]
                gathered = {}
                for future in as_completed(futures):
                    item = future.result()
                    gathered[item[0]] = item
        else:
            gathered = {}
            for index, name in enumerate(artists, start=1):
                gathered[index] = tracked_lookup(index, name)

        entries_by_requested: dict[str, PreviewArtist] = {}
        matched_artists: dict[str, Artist] = {}
        for index, artist_name in enumerate(artists, start=1):
            _index, artist, tracks, note = gathered[index]
            if not artist:
                self.log(f"  {note}: {artist_name}")
                entry = PreviewArtist(artist_name, note=note)
                preview.artists.append(entry)
                entries_by_requested[artist_name.casefold()] = entry
                continue
            tracks = self._filter(tracks, options, seen_titles)
            if options.requested_count and len(tracks) < options.requested_count:
                self.log(f"  Only {len(tracks)} of {options.requested_count} requested tracks available for {artist.name} after filters.")
            accepted: list[Track] = []
            for track in tracks:
                if track.id not in seen_track_ids:
                    accepted.append(track)
                    seen_track_ids.add(track.id)
            entry = PreviewArtist(artist_name, artist.name, accepted, profile_image_url=artist.profile_image_url)
            preview.artists.append(entry)
            entries_by_requested[artist_name.casefold()] = entry
            matched_artists[artist_name.casefold()] = artist
            if options.requested_count and accepted:
                self.log(f"  Added {len(accepted)} catalog track(s) from {artist.name}.")

        if options.include_liked_tracks or options.include_playlist_tracks:
            library_tracks: list[Track] = []
            if options.include_liked_tracks:
                self.log("Reading liked/saved songs from your library…")
                library_tracks.extend(self.adapter.get_liked_tracks())
            if options.include_playlist_tracks:
                playlists = {playlist.id: playlist for playlist in self.adapter.get_user_playlists()}
                chosen = (playlists.values() if options.all_library_playlists else
                          (playlists[playlist_id] for playlist_id in options.selected_playlist_ids if playlist_id in playlists))
                for playlist in chosen:
                    self.log(f"Reading selected playlist: {playlist.name}")
                    library_tracks.extend(self.adapter.get_playlist_tracks(playlist))
            self._add_library_matches(
                preview, entries_by_requested, matched_artists, library_tracks,
                options, seen_track_ids, seen_titles,
            )
        if not preview.tracks:
            raise RuntimeError("No tracks matched the selected song sources and filters. Try widening the release window or changing the filters.")
        return preview

    def _add_library_matches(self, preview: PlaylistPreview,
                             entries_by_requested: dict[str, PreviewArtist],
                             matched_artists: dict[str, Artist], library_tracks: list[Track],
                             options: PlaylistOptions, seen_track_ids: set[str],
                             seen_titles: set[str]) -> None:
        """Add user-library tracks that credit one of the accepted lineup artists."""
        added = 0
        for requested_key, artist in matched_artists.items():
            entry = entries_by_requested[requested_key]
            matching = [replace(track, selection_source="library") for track in library_tracks
                        if self._library_track_matches(track, artist, options.include_collaborations)]
            matching = self._filter(matching, options, seen_titles)
            for track in matching:
                if track.id not in seen_track_ids:
                    entry.tracks.append(track)
                    seen_track_ids.add(track.id)
                    added += 1
        sources: list[str] = []
        if options.include_liked_tracks:
            sources.append("liked/saved songs")
        if options.include_playlist_tracks:
            sources.append("selected playlists")
        self.log(f"  Added {added} matching track(s) from {', '.join(sources)}.")

    @staticmethod
    def _library_track_matches(track: Track, artist: Artist, include_collaborations: bool) -> bool:
        target_name = artist.name.casefold()
        raw_artists = track.raw.get("artists", []) if isinstance(track.raw, dict) else getattr(track.raw, "artists", [])
        credits: list[tuple[str, str | None]] = []
        for credited in raw_artists or []:
            if isinstance(credited, dict):
                credits.append((str(credited.get("name", "")), str(credited.get("id")) if credited.get("id") else None))
            else:
                credits.append((str(getattr(credited, "name", "")), str(getattr(credited, "id", "")) or None))
        text_credits = [name.strip() for name in re.split(r"\s*(?:,|&|\bfeat\.?\b|\bft\.?\b)\s*", track.artist_name, flags=re.IGNORECASE) if name.strip()]
        if not credits:
            credits = [(name, None) for name in text_credits]
        candidates = credits if include_collaborations else credits[:1]
        return any(name.casefold() == target_name or (identifier and identifier == artist.id)
                   for name, identifier in candidates)

    def create(self, playlist_name: str, tracks: list[Track], description: str = "") -> PlaylistResult:
        if not tracks:
            raise RuntimeError("Select at least one track before creating the playlist.")
        self.log(f"Creating playlist with {len(tracks)} approved tracks…")
        return self.adapter.create_playlist(playlist_name, tracks, description)

    def build(self, artists: list[str], playlist_name: str, songs_per_artist: int = 5,
              track_source: str = "popular") -> PlaylistResult:
        """Compatibility convenience method for non-interactive callers."""
        options = PlaylistOptions(
            include_popular=track_source == "popular",
            popular_song_count=songs_per_artist,
            include_recent=track_source == "recent",
            recent_song_count=songs_per_artist,
        )
        preview = self.collect(artists, options)
        return self.create(playlist_name, preview.tracks)

    def _filter(self, tracks: list[Track], options: PlaylistOptions, seen_titles: set[str]) -> list[Track]:
        cutoff = options.release_start or (date.today() - timedelta(days=options.released_within_days) if options.released_within_days else None)
        # A rolling "last N days" range ends today. Explicit custom ranges
        # provide their own end date, including the future-facing date mode.
        end_date = options.release_end or (date.today() if options.released_within_days else None)
        output: list[Track] = []
        for track in tracks:
            title_key = re.sub(r"\s*\([^)]*\)|\s*\[[^]]*\]", "", track.title).casefold().strip()
            if options.skip_remixes and re.search(r"\b(remix|mix|vip|edit)\b", track.title, re.IGNORECASE):
                continue
            if options.singles_only and track.release_type not in (None, "single"):
                continue
            if cutoff or end_date:
                if not track.release_date:
                    # A release-window filter must not silently admit music
                    # whose date cannot be verified by the provider.
                    continue
                try:
                    released = date.fromisoformat(track.release_date[:10])
                    if cutoff and released < cutoff:
                        continue
                    if end_date and released > end_date:
                        continue
                except ValueError:
                    continue
            if options.dedupe_titles and title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            output.append(track)
        return output
