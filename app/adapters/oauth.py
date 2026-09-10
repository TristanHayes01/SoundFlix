"""A short-lived loopback receiver for PKCE desktop authorization callbacks."""
from __future__ import annotations
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse
import base64
import hashlib
import os
import secrets
import webbrowser


@dataclass
class PKCE:
    verifier: str
    challenge: str

    @classmethod
    def create(cls) -> "PKCE":
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return cls(verifier, challenge)


def open_default_browser(url: str) -> None:
    """Use Windows' URL association, not a Python/browser-specific preference."""
    # tidalapi's device-login object currently returns values such as
    # "link.tidal.com/ABCDE" rather than an absolute URL. Windows startfile
    # interprets a scheme-less value as a filesystem path, so normalize it.
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    if os.name == "nt":
        # startfile delegates the URL to the user's configured default HTTP handler.
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        webbrowser.open(url)


class OAuthCallback:
    """Captures exactly one local callback and validates its CSRF state value."""
    def __init__(self, redirect_uri: str, expected_state: str):
        parsed = urlparse(redirect_uri)
        self._server = HTTPServer((parsed.hostname or "127.0.0.1", parsed.port or 80), self._handler())
        self._state = expected_state
        self._event, self._params = Event(), {}

    def _handler(self):
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer._params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                body = b"Authorization received. You can close this tab and return to SoundFlix."
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                outer._event.set()
            def log_message(self, *_):  # Keep callback noise out of terminal/logs.
                pass
        return Handler

    def authorize(self, url: str, timeout_seconds: int = 180) -> str:
        Thread(target=self._server.handle_request, daemon=True).start()
        open_default_browser(url)
        if not self._event.wait(timeout_seconds):
            raise RuntimeError("Login timed out. Start Login again and finish it in the browser.")
        if self._params.get("state") != self._state:
            raise RuntimeError("OAuth state mismatch; the login response was rejected.")
        if "error" in self._params:
            raise RuntimeError(f"Authorization declined: {self._params['error']}")
        code = self._params.get("code")
        if not code:
            raise RuntimeError("Login callback did not contain an authorization code.")
        return code
