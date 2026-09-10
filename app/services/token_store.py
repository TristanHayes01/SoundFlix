"""Small credential-vault wrapper; avoids leaving refresh tokens in files."""
from __future__ import annotations
import json
import keyring


class TokenStore:
    SERVICE = "SoundFlix"
    LEGACY_SERVICE = "FlyerPlaylistBuilder"

    def load(self, provider: str) -> dict | None:
        value = keyring.get_password(self.SERVICE, provider)
        # Preserve existing authorized sessions after the application's rename.
        if not value:
            value = keyring.get_password(self.LEGACY_SERVICE, provider)
            if value:
                keyring.set_password(self.SERVICE, provider, value)
        return json.loads(value) if value else None

    def save(self, provider: str, payload: dict) -> None:
        keyring.set_password(self.SERVICE, provider, json.dumps(payload))

    def clear(self, provider: str) -> None:
        for service in (self.SERVICE, self.LEGACY_SERVICE):
            try:
                keyring.delete_password(service, provider)
            except keyring.errors.PasswordDeleteError:
                pass
