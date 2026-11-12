"""TIDAL adapter built around tidalapi's supported interactive OAuth helper."""
from __future__ import annotations
from datetime import datetime
import re
import tidalapi
from app.models import Artist, PlaylistResult, Track
from app.services.token_store import TokenStore
from .base import BaseMusicAdapter
from .oauth import open_default_browser

_TIDAL_DEFAULT_ARTIST_PICTURE = "1e01cdb6-f15d-4d8b-8440-a047976c1cac"


class TidalAdapter(BaseMusicAdapter):
    name = "TIDAL"

    def __init__(self) -> None:
        self.session = tidalapi.Session()
        self.tokens = TokenStore()

    def authenticate(self, log) -> None:
        cached = self.tokens.load("tidal")
        if cached:
            try:
                # TokenStore stores JSON, while tidalapi represents expiry_time as datetime.
                expiry_time = cached["expiry_time"]
                if isinstance(expiry_time, str):
                    expiry_time = datetime.fromisoformat(expiry_time)
                if self.session.load_oauth_session(
                    cached["token_type"], cached["access_token"], cached["refresh_token"], expiry_time
                ) and self.session.check_login():
                    log("TIDAL session restored from secure storage."); return
            except Exception:
                self.tokens.clear("tidal")
        log("Opening TIDAL sign-in in your browser…")
        login, future = self.session.login_oauth()
        open_default_browser(login.verification_uri_complete)
        # This blocks only the calling worker thread; CustomTkinter stays responsive.
        future.result(timeout=300)
        if not self.session.check_login():
            raise RuntimeError("TIDAL login did not complete.")
        self.tokens.save("tidal", {
            "token_type": self.session.token_type, "access_token": self.session.access_token,
            "refresh_token": self.session.refresh_token,
            # datetime is not JSON serializable; ISO 8601 round-trips cleanly on the next login.
            "expiry_time": self.session.expiry_time.isoformat(),
        })
        log("TIDAL authenticated.")

    def _require_login(self) -> None:
        if not self.session.check_login():
            raise RuntimeError("TIDAL is not authenticated. Press Login first.")

    def search_artist(self, query: str) -> Artist | None:
        artists = self.search_artists(query)
        return next((artist for artist in artists if artist.name.casefold() == query.casefold()), artists[0] if artists else None)

    def search_artists(self, query: str, limit: int = 10) -> list[Artist]:
        self._require_login()
        result = self.session.search(query, models=[tidalapi.Artist], limit=limit)
        artists = result.get("artists", []) if isinstance(result, dict) else result
        return [Artist(
            str(item.id), item.name, item,
            getattr(item, "share_url", None) or getattr(item, "url", None) or f"https://tidal.com/artist/{item.id}",
            self._artist_image_url(item),
        ) for item in artists]

    def artist_from_profile_url(self, url: str) -> Artist | None:
        self._require_login()
        match = re.search(r"/artist/(\d+)", url)
        if not match:
            raise RuntimeError("Paste a TIDAL artist profile link.")
        raw = self.session.artist(match.group(1))
        return Artist(
            str(raw.id), raw.name, raw,
            getattr(raw, "share_url", None) or getattr(raw, "url", None) or url,
            self._artist_image_url(raw),
        )

    @staticmethod
    def _artist_image_url(artist) -> str | None:
        """Return TIDAL's real artist portrait, never its generic microphone asset.

        ``tidalapi`` fills a missing ``picture`` with a known default UUID.  The
        prior workaround suppressed *every* image to avoid that one placeholder;
        instead, only suppress the default and keep genuine artist portraits.
        """
        picture = getattr(artist, "picture", None)
        if not picture or picture == _TIDAL_DEFAULT_ARTIST_PICTURE:
            return None
        try:
            return artist.image(320)
        except (AttributeError, TypeError, ValueError):
            # A search result can occasionally contain incomplete image metadata.
            # The UI will render its neutral placeholder in that case.
            return None

    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        self._require_login()
        # tidalapi has used both names across releases, so retain a safe compatibility path.
        artist_method = getattr(artist.raw, "get_top_tracks", None)
        session_method = getattr(self.session, "get_artist_top_tracks", None)
        if artist_method:
            entries = artist_method(limit=limit)
        elif session_method:
            entries = session_method(artist.id, limit=limit)
        else:
            raise RuntimeError("Installed tidalapi lacks an artist top-tracks method; update tidalapi.")
        return [Track(str(t.id), t.name, artist.name, str(t.id), getattr(t, "popularity", None), t, str(getattr(t, "release_date", "") or ""), None) for t in entries]

    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        """Use the artist's albums and EP/singles, ordered by their release date."""
        self._require_login()
        albums_method = getattr(artist.raw, "get_albums", None)
        singles_method = getattr(artist.raw, "get_ep_singles", None)
        if not albums_method:
            raise RuntimeError("Installed tidalapi lacks artist release methods; update tidalapi.")
        releases = list(albums_method(limit=50))
        if singles_method:
            releases.extend(singles_method(limit=50))
        # `release_date` is a date/datetime in current tidalapi releases; str also handles
        # older wrapper versions that return an ISO string or a missing value.
        releases.sort(key=lambda album: str(getattr(album, "release_date", None) or getattr(album, "available_release_date", None) or ""), reverse=True)
        found: list[Track] = []
        seen: set[str] = set()
        for release in releases:
            for track in release.tracks(limit=100):
                track_id = str(track.id)
                if track_id in seen:
                    continue
                found.append(Track(track_id, track.name, artist.name, track_id, getattr(track, "popularity", None), track, str(getattr(release, "release_date", "") or ""), getattr(release, "type", None)))
                seen.add(track_id)
                if len(found) == limit:
                    return found
        return found

    def create_playlist(self, name: str, tracks: list[Track], description: str = "") -> PlaylistResult:
        self._require_login()
        playlist = self.session.user.create_playlist(name, description or "Created by SoundFlix")
        playlist.add([int(track.id) for track in tracks])
        return PlaylistResult(name, getattr(playlist, "share_url", None), len(tracks))
