"""SoundCloud OAuth 2.1 PKCE adapter implemented directly against the public API."""
from __future__ import annotations
from urllib.parse import urlencode
import secrets
import time
import requests
from app.config import settings
from app.models import Artist, PlaylistResult, Track
from app.services.token_store import TokenStore
from .base import BaseMusicAdapter
from .oauth import OAuthCallback, PKCE


class SoundCloudAdapter(BaseMusicAdapter):
    name = "SoundCloud"
    API = "https://api.soundcloud.com"

    def __init__(self) -> None:
        self.tokens, self.session, self.access_token = TokenStore(), requests.Session(), None

    def authenticate(self, log) -> None:
        if not settings.soundcloud_client_id:
            raise RuntimeError("Set SOUNDCLOUD_CLIENT_ID in .env before logging in.")
        cached = self.tokens.load("soundcloud")
        if cached and cached.get("expires_at", 0) > time.time() + 30:
            self.access_token = cached["access_token"]; log("SoundCloud session restored from secure storage."); return
        if cached and cached.get("refresh_token"):
            token = self._exchange({"grant_type": "refresh_token", "refresh_token": cached["refresh_token"]})
            if token:
                self._save(token); log("SoundCloud access token refreshed."); return
        pkce, state = PKCE.create(), secrets.token_urlsafe(24)
        params = {
            "client_id": settings.soundcloud_client_id, "redirect_uri": settings.soundcloud_redirect_uri,
            "response_type": "code", "code_challenge": pkce.challenge, "code_challenge_method": "S256",
            "state": state,
        }
        log("Opening SoundCloud authorization in your browser…")
        code = OAuthCallback(settings.soundcloud_redirect_uri, state).authorize(
            "https://secure.soundcloud.com/authorize?" + urlencode(params))
        token = self._exchange({
            "grant_type": "authorization_code", "client_id": settings.soundcloud_client_id,
            "redirect_uri": settings.soundcloud_redirect_uri, "code": code, "code_verifier": pkce.verifier,
        })
        if not token:
            raise RuntimeError("SoundCloud did not return an access token.")
        self._save(token); log("SoundCloud authenticated.")

    def _exchange(self, data: dict) -> dict | None:
        response = requests.post("https://secure.soundcloud.com/oauth/token", data=data, timeout=25)
        return response.json() if response.ok else None

    def _save(self, payload: dict) -> None:
        payload["expires_at"] = time.time() + int(payload.get("expires_in", 3600))
        self.tokens.save("soundcloud", payload); self.access_token = payload["access_token"]

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not self.access_token:
            raise RuntimeError("SoundCloud is not authenticated.")
        response = self.session.request(method, self.API + path, headers={
            "Authorization": f"OAuth {self.access_token}", "Accept": "application/json",
            "Content-Type": "application/json"}, timeout=25, **kwargs)
        if response.status_code == 429:
            raise RuntimeError("SoundCloud rate limit reached. Wait briefly and retry.")
        if response.status_code == 401:
            raise RuntimeError("SoundCloud session expired; press Login again.")
        response.raise_for_status()
        return response

    def search_artist(self, query: str) -> Artist | None:
        artists = self.search_artists(query)
        return next((artist for artist in artists if artist.name.casefold() == query.casefold()), artists[0] if artists else None)

    def search_artists(self, query: str, limit: int = 10) -> list[Artist]:
        items = self._request("GET", "/users", params={"q": query, "limit": min(limit, 200)}).json()
        return [Artist(str(item["id"]), item.get("username", "Unknown artist"), item,
                       item.get("permalink_url") or f"https://soundcloud.com/{item.get('permalink', '')}",
                       item.get("avatar_url")) for item in items]

    def artist_from_profile_url(self, url: str) -> Artist | None:
        item = self._request("GET", "/resolve", params={"url": url}).json()
        if item.get("kind") not in (None, "user"):
            raise RuntimeError("Paste a SoundCloud artist profile link, not a track or playlist link.")
        return Artist(str(item["id"]), item.get("username", "Unknown artist"), item,
                      item.get("permalink_url") or url, item.get("avatar_url"))

    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        # SoundCloud exposes no global popularity endpoint. The documented track search is ranked locally.
        candidates = self._artist_tracks(artist)
        candidates.sort(key=lambda x: (x.get("favoritings_count", 0), x.get("playback_count", 0)), reverse=True)
        return [Track(str(x["id"]), x["title"], artist.name, str(x["id"]), None, x, x.get("created_at"), "single") for x in candidates[:limit]]

    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        candidates = self._artist_tracks(artist)
        # SoundCloud's created_at is ISO 8601 and therefore sorts safely as text.
        candidates.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return [Track(str(x["id"]), x["title"], artist.name, str(x["id"]), None, x, x.get("created_at"), "single") for x in candidates[:limit]]

    def _artist_tracks(self, artist: Artist) -> list[dict]:
        """Return this user's playable tracks once; callers decide their ranking policy."""
        payload = self._request("GET", "/tracks", params={
            "q": artist.name, "user_id": artist.id, "access": "playable", "limit": 100,
        }).json()
        items = payload.get("collection", payload) if isinstance(payload, dict) else payload
        return [x for x in items if str(x.get("user_id")) == artist.id and x.get("streamable", True)]

    def create_playlist(self, name: str, tracks: list[Track], description: str = "") -> PlaylistResult:
        payload = {"playlist": {
            "title": name, "description": description or "Created by SoundFlix", "sharing": "private",
            "tracks": [{"id": int(track.id)} for track in tracks],
        }}
        playlist = self._request("POST", "/playlists", json=payload).json()
        return PlaylistResult(name, playlist.get("permalink_url"), len(tracks))
