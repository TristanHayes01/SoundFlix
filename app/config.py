"""Configuration loading. All secrets are read from environment variables."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from dotenv import load_dotenv


def _dotenv_path() -> Path:
    """Use the project folder in development and the app folder when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parents[1] / ".env"


load_dotenv(_dotenv_path())  # Never overwrite explicitly supplied environment values.


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str = os.getenv("SPOTIFY_CLIENT_ID", "")
    spotify_redirect_uri: str = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8765/callback")
    soundcloud_client_id: str = os.getenv("SOUNDCLOUD_CLIENT_ID", "")
    soundcloud_redirect_uri: str = os.getenv("SOUNDCLOUD_REDIRECT_URI", "http://127.0.0.1:8766/callback")
    apple_team_id: str = os.getenv("APPLE_MUSIC_TEAM_ID", "")
    apple_key_id: str = os.getenv("APPLE_MUSIC_KEY_ID", "")
    apple_private_key_path: str = os.getenv("APPLE_MUSIC_PRIVATE_KEY_PATH", "")
    apple_storefront: str = os.getenv("APPLE_MUSIC_STOREFRONT", "us")
    apple_music_user_token: str = os.getenv("APPLE_MUSIC_USER_TOKEN", "")

    @property
    def apple_key_path(self) -> Path:
        return Path(self.apple_private_key_path).expanduser()


settings = Settings()
