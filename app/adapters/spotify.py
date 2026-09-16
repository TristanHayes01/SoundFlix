"""Spotify adapter using Authorization Code + PKCE and the current Web API."""
from __future__ import annotations
from urllib.parse import urlencode
import base64
import time
import requests
import spotipy
from app.config import settings
from app.models import Artist, PlaylistResult, Track
from app.services.token_store import TokenStore
from .base import BaseMusicAdapter
from .oauth import OAuthCallback, PKCE
import secrets


class SpotifyAdapter(BaseMusicAdapter):
    name = "Spotify"
    API = "https://api.spotify.com/v1"

    def __init__(self) -> None:
        self.tokens = TokenStore()
        self.session = requests.Session()
        self.access_token: str | None = None
        self.client: spotipy.Spotify | None = None

    def authenticate(self, log) -> None:
        if not settings.spotify_client_id:
            raise RuntimeError("Set SPOTIFY_CLIENT_ID in .env before logging in.")
        cached = self.tokens.load("spotify")
        if cached and cached.get("expires_at", 0) > time.time() + 30:
            self._set_access_token(cached["access_token"]); log("Spotify session restored from secure storage."); return
        if cached and cached.get("refresh_token"):
            response = requests.post("https://accounts.spotify.com/api/token", data={
                "grant_type": "refresh_token", "refresh_token": cached["refresh_token"],
                "client_id": settings.spotify_client_id,
            }, timeout=20)
            if response.ok:
                payload = response.json()
                payload["refresh_token"] = payload.get("refresh_token", cached["refresh_token"])
                self._save(payload); log("Spotify access token refreshed."); return
        pkce, state = PKCE.create(), secrets.token_urlsafe(24)
        params = {
            "client_id": settings.spotify_client_id, "response_type": "code",
            "redirect_uri": settings.spotify_redirect_uri, "state": state,
            "scope": "playlist-modify-private playlist-modify-public ugc-image-upload",
            "code_challenge_method": "S256", "code_challenge": pkce.challenge,
        }
        log("Opening Spotify authorization in your browser…")
        code = OAuthCallback(settings.spotify_redirect_uri, state).authorize(
            "https://accounts.spotify.com/authorize?" + urlencode(params))
        response = requests.post("https://accounts.spotify.com/api/token", data={
            "client_id": settings.spotify_client_id, "grant_type": "authorization_code",
            "code": code, "redirect_uri": settings.spotify_redirect_uri, "code_verifier": pkce.verifier,
        }, timeout=20)
        response.raise_for_status(); self._save(response.json()); log("Spotify authenticated.")

    def _save(self, payload: dict) -> None:
        payload["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
        self.tokens.save("spotify", payload); self._set_access_token(payload["access_token"])

    def _set_access_token(self, value: str) -> None:
        """Use spotipy for catalog operations; direct REST remains for changed playlist endpoints."""
        self.access_token = value
        self.client = spotipy.Spotify(auth=value, requests_timeout=25, retries=0)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not self.access_token:
            raise RuntimeError("Spotify is not authenticated.")
        response = self.session.request(method, self.API + path, headers={
            "Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}, timeout=25, **kwargs)
        if response.status_code == 429:
            raise RuntimeError(f"Spotify rate limit reached; retry after {response.headers.get('Retry-After', 'a short wait')} seconds.")
        if response.status_code == 401:
            raise RuntimeError("Spotify session expired; press Login again.")
        response.raise_for_status()
        return response

    def search_artist(self, query: str) -> Artist | None:
        if not self.client:
            raise RuntimeError("Spotify is not authenticated.")
        items = self.client.search(q=query, type="artist", limit=5).get("artists", {}).get("items", [])
        # Exact display-name match wins over Spotify's relevance ordering.
        match = next((x for x in items if x["name"].casefold() == query.casefold()), items[0] if items else None)
        return Artist(match["id"], match["name"], match) if match else None

    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        # /artists/{id}/top-tracks was removed in 2026. Rank artist-constrained search tracks instead.
        if not self.client:
            raise RuntimeError("Spotify is not authenticated.")
        data = self.client.search(q=f"artist:{artist.name}", type="track", limit=10)
        candidates = [x for x in data.get("tracks", {}).get("items", []) if any(a["id"] == artist.id for a in x.get("artists", []))]
        candidates.sort(key=lambda x: x.get("popularity", 0), reverse=True)
        return [Track(x["id"], x["name"], ", ".join(a["name"] for a in x["artists"]), x["uri"], x.get("popularity"), x, x.get("album", {}).get("release_date"), x.get("album", {}).get("album_type")) for x in candidates[:limit]]

    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        """Collect tracks from the artist's latest albums and singles, newest first."""
        if not self.client:
            raise RuntimeError("Spotify is not authenticated.")
        # Spotify caps this endpoint at 10 per page; its default order is newest releases first.
        releases = self.client.artist_albums(artist.id, album_type="album,single", country="US", limit=10).get("items", [])
        releases.sort(key=lambda album: album.get("release_date", ""), reverse=True)
        found: list[Track] = []
        seen: set[str] = set()
        for album in releases:
            tracks = self.client.album_tracks(album["id"], limit=50).get("items", [])
            # Album tracks inherit the album release date. Reverse numerical order makes a
            # same-day release deterministic while newer albums still take priority.
            tracks.sort(key=lambda track: (track.get("disc_number", 0), track.get("track_number", 0)), reverse=True)
            for track in tracks:
                if track["id"] in seen:
                    continue
                found.append(Track(track["id"], track["name"], ", ".join(a["name"] for a in track["artists"]), track["uri"], None, track, album.get("release_date"), album.get("album_type")))
                seen.add(track["id"])
                if len(found) == limit:
                    return found
        return found

    def create_playlist(self, name: str, tracks: list[Track], description: str = "", artwork: bytes | None = None) -> PlaylistResult:
        playlist = self._request("POST", "/me/playlists", json={"name": name, "public": False, "description": description or "Created by SoundFlix"}).json()
        for offset in range(0, len(tracks), 100):
            self._request("POST", f"/playlists/{playlist['id']}/items", json={"uris": [t.uri for t in tracks[offset:offset + 100]]})
        if artwork:
            # Spotify accepts base64-encoded JPEG artwork. It requires the ugc-image-upload scope.
            response = self.session.put(f"{self.API}/playlists/{playlist['id']}/images", headers={
                "Authorization": f"Bearer {self.access_token}", "Content-Type": "image/jpeg"},
                data=base64.b64encode(artwork), timeout=25)
            # Cover upload is optional; playlist creation remains successful if the scope is absent.
            if not response.ok:
                pass
        return PlaylistResult(name, playlist.get("external_urls", {}).get("spotify"), len(tracks))
