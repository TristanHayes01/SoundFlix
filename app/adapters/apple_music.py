"""Apple Music REST adapter with locally signed developer JWT and Music User Token."""
from __future__ import annotations
from pathlib import Path
import time
import jwt
import requests
from app.config import settings
from app.models import Artist, PlaylistResult, Track
from app.services.token_store import TokenStore
from .base import BaseMusicAdapter


class AppleMusicAdapter(BaseMusicAdapter):
    name = "Apple Music"
    API = "https://api.music.apple.com/v1"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.developer_token: str | None = None
        self.user_token = settings.apple_music_user_token
        self.tokens = TokenStore()

    def authenticate(self, log) -> None:
        if (self.tokens.load("apple_music") or {}).get("signed_out"):
            raise RuntimeError("Apple Music is logged out locally. Use Login in Settings to re-enable it.")
        if not all([settings.apple_team_id, settings.apple_key_id, settings.apple_private_key_path, self.user_token]):
            raise RuntimeError("Apple Music needs Team ID, Key ID, private-key path, and Music User Token in .env.")
        key_path = settings.apple_key_path
        if not key_path.is_file():
            raise RuntimeError(f"Apple Music private key was not found: {key_path}")
        # Apple developer tokens may last up to six months; use one-hour tokens for local least privilege.
        now = int(time.time())
        self.developer_token = jwt.encode(
            {"iss": settings.apple_team_id, "iat": now, "exp": now + 3600},
            key_path.read_text(encoding="utf-8"), algorithm="ES256", headers={"kid": settings.apple_key_id},
        )
        # A lightweight authenticated request detects copied/expired Music User Tokens early.
        self._request("GET", "/me/storefront")
        log("Apple Music developer and user tokens validated.")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not self.developer_token:
            raise RuntimeError("Apple Music is not authenticated.")
        response = self.session.request(method, self.API + path, headers={
            "Authorization": f"Bearer {self.developer_token}", "Music-User-Token": self.user_token,
            "Content-Type": "application/json"}, timeout=25, **kwargs)
        if response.status_code == 429:
            raise RuntimeError("Apple Music rate limit reached. Wait briefly and retry.")
        if response.status_code in (401, 403):
            raise RuntimeError("Apple Music rejected the developer or Music User Token. Generate a new user token and press Login.")
        response.raise_for_status()
        return response

    def search_artist(self, query: str) -> Artist | None:
        data = self._request("GET", f"/catalog/{settings.apple_storefront}/search", params={
            "term": query, "types": "artists", "limit": 10,
        }).json()
        artists = data.get("results", {}).get("artists", {}).get("data", [])
        exact = next((a for a in artists if a["attributes"]["name"].casefold() == query.casefold()), artists[0] if artists else None)
        return Artist(exact["id"], exact["attributes"]["name"], exact) if exact else None

    def get_top_5_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        # The catalog top-songs view reflects Apple Music editorial/catalog ordering when available.
        data = self._request("GET", f"/catalog/{settings.apple_storefront}/artists/{artist.id}/view/top-songs", params={"limit": limit}).json()
        songs = data.get("data", [])
        if not songs:
            # Catalog fallback; restrict the matching results to the selected artist's name.
            search = self._request("GET", f"/catalog/{settings.apple_storefront}/search", params={
                "term": artist.name, "types": "songs", "limit": 25,
            }).json()
            songs = [x for x in search.get("results", {}).get("songs", {}).get("data", [])
                     if artist.name.casefold() in x["attributes"].get("artistName", "").casefold()][:limit]
        return [Track(x["id"], x["attributes"]["name"], x["attributes"]["artistName"], x["id"], None, x) for x in songs[:limit]]

    def get_recent_tracks(self, artist: Artist, limit: int = 5) -> list[Track]:
        """Take songs from the artist's newest catalog albums, newest release first."""
        try:
            releases = self._request("GET", f"/catalog/{settings.apple_storefront}/artists/{artist.id}/albums", params={"limit": 25}).json().get("data", [])
            releases.sort(key=lambda album: album.get("attributes", {}).get("releaseDate", ""), reverse=True)
            songs: list[dict] = []
            seen: set[str] = set()
            for album in releases:
                album_songs = self._request("GET", f"/catalog/{settings.apple_storefront}/albums/{album['id']}/tracks", params={"limit": 100}).json().get("data", [])
                for song in album_songs:
                    if song["id"] not in seen:
                        songs.append(song)
                        seen.add(song["id"])
                    if len(songs) == limit:
                        break
                if len(songs) == limit:
                    break
        except requests.HTTPError:
            # Some storefront/catalog combinations omit the artist-albums relationship.
            songs = []
        if not songs:
            search = self._request("GET", f"/catalog/{settings.apple_storefront}/search", params={
                "term": artist.name, "types": "songs", "limit": 25,
            }).json()
            songs = [song for song in search.get("results", {}).get("songs", {}).get("data", [])
                     if artist.name.casefold() in song["attributes"].get("artistName", "").casefold()]
            songs.sort(key=lambda song: song["attributes"].get("releaseDate", ""), reverse=True)
        return [Track(song["id"], song["attributes"]["name"], song["attributes"]["artistName"], song["id"], None, song) for song in songs[:limit]]

    def create_playlist(self, name: str, tracks: list[Track]) -> PlaylistResult:
        data = self._request("POST", "/me/library/playlists", json={
            "attributes": {"name": name, "description": {"standard": "Created by SoundFlix"}},
            "relationships": {"tracks": {"data": [{"id": t.id, "type": "songs"} for t in tracks]}},
        }).json()
        playlist = data["data"][0]
        return PlaylistResult(name, playlist.get("href"), len(tracks))
