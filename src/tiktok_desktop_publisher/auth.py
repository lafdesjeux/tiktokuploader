from __future__ import annotations

import hashlib
import secrets
import string
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"


class OAuthError(RuntimeError):
    pass


@dataclass
class TokenResponse:
    access_token: str
    refresh_token: str
    open_id: str
    scope: str
    expires_in: int
    refresh_expires_in: int
    token_type: str = "Bearer"

    @classmethod
    def from_payload(cls, payload: dict) -> "TokenResponse":
        if payload.get("error"):
            raise OAuthError(payload.get("error_description") or payload["error"])
        required = ["access_token", "refresh_token", "open_id"]
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise OAuthError(f"TikTok token response is missing: {', '.join(missing)}")
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            open_id=str(payload["open_id"]),
            scope=str(payload.get("scope", "")),
            expires_in=int(payload.get("expires_in", 0)),
            refresh_expires_in=int(payload.get("refresh_expires_in", 0)),
            token_type=str(payload.get("token_type", "Bearer")),
        )


class OAuthDesktopFlow:
    def __init__(
        self,
        client_key: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str,
        timeout_seconds: int = 240,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.client_key = client_key.strip()
        self.client_secret = client_secret.strip()
        self.redirect_uri = redirect_uri.strip()
        self.scopes = scopes.strip()
        self.timeout_seconds = timeout_seconds
        self.log = log or (lambda _message: None)

    @staticmethod
    def _random_unreserved(length: int) -> str:
        alphabet = string.ascii_letters + string.digits + "-._~"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def authorize(self) -> TokenResponse:
        self._validate_configuration()
        parsed = urlparse(self.redirect_uri)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port
        callback_path = parsed.path or "/"
        if port is None:
            raise OAuthError("The desktop redirect URI must include a port number.")

        state = secrets.token_urlsafe(32)
        code_verifier = self._random_unreserved(64)
        code_challenge = hashlib.sha256(code_verifier.encode("ascii")).hexdigest()
        query = urlencode(
            {
                "client_key": self.client_key,
                "response_type": "code",
                "scope": self.scopes,
                "redirect_uri": self.redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        authorization_url = f"{AUTHORIZE_URL}?{query}"

        result: dict[str, str] = {}
        completed = threading.Event()

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
                incoming = urlparse(self.path)
                if incoming.path.rstrip("/") != callback_path.rstrip("/"):
                    self.send_response(404)
                    self.end_headers()
                    return
                values = parse_qs(incoming.query)
                for key in ("code", "state", "error", "error_description", "scopes"):
                    if values.get(key):
                        result[key] = values[key][0]
                body = (
                    "<!doctype html><html><body style='font-family:system-ui;padding:3rem'>"
                    "<h1>Authorization received</h1>"
                    "<p>You can return to TikTok Desktop Publisher.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                completed.set()

            def log_message(self, _format, *_args):
                return

        server = HTTPServer((host, port), CallbackHandler)
        server.timeout = 1
        self.log("Opening TikTok authorization in the default browser…")
        webbrowser.open(authorization_url, new=1, autoraise=True)

        deadline = time.monotonic() + self.timeout_seconds
        try:
            while not completed.is_set() and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()

        if not completed.is_set():
            raise OAuthError("TikTok authorization timed out.")
        if result.get("state") != state:
            raise OAuthError("OAuth state mismatch. Authorization was rejected for security reasons.")
        if result.get("error"):
            raise OAuthError(result.get("error_description") or result["error"])
        code = result.get("code")
        if not code:
            raise OAuthError("TikTok did not return an authorization code.")
        return self.exchange_code(code, code_verifier)

    def exchange_code(self, code: str, code_verifier: str) -> TokenResponse:
        response = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=60,
        )
        payload = self._json_or_error(response)
        return TokenResponse.from_payload(payload)

    def refresh(self, refresh_token: str) -> TokenResponse:
        response = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=60,
        )
        payload = self._json_or_error(response)
        return TokenResponse.from_payload(payload)

    def revoke(self, access_token: str) -> None:
        response = requests.post(
            REVOKE_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "token": access_token,
            },
            timeout=60,
        )
        if response.status_code >= 400:
            raise OAuthError(f"TikTok revoke failed: HTTP {response.status_code} {response.text}")

    def _validate_configuration(self) -> None:
        if not self.client_key or not self.client_secret:
            raise OAuthError("Client key and client secret are required.")
        parsed = urlparse(self.redirect_uri)
        if parsed.scheme not in {"http", "https"}:
            raise OAuthError("Redirect URI must start with http:// or https://.")
        if parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise OAuthError("Desktop redirect URI host must be localhost or 127.0.0.1.")
        if not parsed.port:
            raise OAuthError("Desktop redirect URI must include a port.")

    @staticmethod
    def _json_or_error(response: requests.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError(f"TikTok returned invalid JSON: HTTP {response.status_code}") from exc
        if response.status_code >= 400:
            raise OAuthError(
                payload.get("error_description")
                or payload.get("message")
                or f"TikTok OAuth failed: HTTP {response.status_code}"
            )
        return payload
