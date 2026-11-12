"""Small credential-vault wrapper; avoids leaving refresh tokens in files."""
from __future__ import annotations
import json
import sys
import keyring


class TokenStore:
    # A packaged app must never inherit the developer copy's credentials or
    # playlist history from Windows Credential Manager.  Each Windows user
    # still receives their own vault automatically.
    PACKAGED = bool(getattr(sys, "frozen", False))
    SERVICE = "SoundFlix Desktop" if PACKAGED else "SoundFlix"
    LEGACY_SERVICE = None if PACKAGED else "FlyerPlaylistBuilder"

    def load(self, provider: str) -> dict | None:
        value = keyring.get_password(self.SERVICE, provider)
        # Preserve existing development sessions after the application's
        # rename, but never migrate them into a distributable desktop build.
        if not value and self.LEGACY_SERVICE:
            value = keyring.get_password(self.LEGACY_SERVICE, provider)
            if value:
                keyring.set_password(self.SERVICE, provider, value)
        return json.loads(value) if value else None

    def save(self, provider: str, payload: dict) -> None:
        keyring.set_password(self.SERVICE, provider, json.dumps(payload))

    def clear(self, provider: str) -> None:
        for service in filter(None, (self.SERVICE, self.LEGACY_SERVICE)):
            try:
                keyring.delete_password(service, provider)
            except keyring.errors.PasswordDeleteError:
                pass
