from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

APP_NAME = "TikTokDesktopPublisher"
APP_AUTHOR = "OpenSource"
KEYRING_SERVICE = "tiktok-desktop-publisher"


@dataclass
class AppSettings:
    client_key: str = ""
    redirect_uri: str = "http://127.0.0.1:3455/callback/"
    scopes: str = "user.info.basic,video.publish"
    timezone: str = "Europe/Luxembourg"
    open_id: str = ""
    token_scope: str = ""
    access_expires_at: str = ""
    refresh_expires_at: str = ""

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "AppSettings":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: values[key] for key in allowed if key in values})


class LocalStore:
    """Store non-secret settings in JSON and secrets in the OS keyring when possible.

    If no usable keyring backend exists, secrets fall back to a user-only JSON file.
    The fallback is intentionally explicit so the application remains usable on
    minimal Linux desktops.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(user_config_dir(APP_NAME, APP_AUTHOR))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.base_dir / "settings.json"
        self.fallback_secrets_path = self.base_dir / "secrets.json"

    def load_settings(self) -> AppSettings:
        if not self.settings_path.exists():
            return AppSettings()
        try:
            return AppSettings.from_dict(json.loads(self.settings_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self._write_private_json(self.settings_path, asdict(settings))

    def _keyring(self):
        try:
            import keyring  # type: ignore
            from keyring.errors import KeyringError  # type: ignore

            # Trigger backend resolution now, rather than failing during a later call.
            keyring.get_keyring()
            return keyring, KeyringError
        except Exception:
            return None, Exception

    def _secret_account(self, client_key: str, name: str) -> str:
        profile = client_key.strip() or "default"
        return f"{profile}:{name}"

    def get_secret(self, client_key: str, name: str) -> str:
        env_name = {
            "client_secret": "TIKTOK_CLIENT_SECRET",
            "access_token": "TIKTOK_ACCESS_TOKEN",
            "refresh_token": "TIKTOK_REFRESH_TOKEN",
        }.get(name)
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]

        keyring, _ = self._keyring()
        if keyring is not None:
            try:
                value = keyring.get_password(KEYRING_SERVICE, self._secret_account(client_key, name))
                if value:
                    return value
            except Exception:
                pass

        data = self._read_fallback_secrets()
        return str(data.get(client_key or "default", {}).get(name, ""))

    def set_secret(self, client_key: str, name: str, value: str) -> None:
        profile = client_key or "default"
        keyring, _ = self._keyring()
        if keyring is not None:
            try:
                keyring.set_password(KEYRING_SERVICE, self._secret_account(profile, name), value)
                return
            except Exception:
                pass

        data = self._read_fallback_secrets()
        data.setdefault(profile, {})[name] = value
        self._write_private_json(self.fallback_secrets_path, data)

    def delete_secret(self, client_key: str, name: str) -> None:
        profile = client_key or "default"
        keyring, _ = self._keyring()
        if keyring is not None:
            try:
                keyring.delete_password(KEYRING_SERVICE, self._secret_account(profile, name))
            except Exception:
                pass
        data = self._read_fallback_secrets()
        if profile in data:
            data[profile].pop(name, None)
            if not data[profile]:
                data.pop(profile, None)
            self._write_private_json(self.fallback_secrets_path, data)

    def _read_fallback_secrets(self) -> dict[str, dict[str, str]]:
        if not self.fallback_secrets_path.exists():
            return {}
        try:
            return json.loads(self.fallback_secrets_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _write_private_json(path: Path, value: Any) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        temporary.replace(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None
