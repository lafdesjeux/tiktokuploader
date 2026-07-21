from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .api import CreatorInfo, TikTokClient
from .auth import OAuthDesktopFlow, TokenResponse
from .config import AppSettings, LocalStore, parse_utc, utc_now
from .queue import PublishQueue


class PublisherService:
    def __init__(
        self,
        store: LocalStore | None = None,
        queue: PublishQueue | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store or LocalStore()
        self.queue = queue or PublishQueue()
        self.log = log or (lambda _message: None)

    def settings(self) -> AppSettings:
        settings = self.store.load_settings()
        if os.environ.get("TIKTOK_CLIENT_KEY"):
            settings.client_key = os.environ["TIKTOK_CLIENT_KEY"]
        if os.environ.get("TIKTOK_REDIRECT_URI"):
            settings.redirect_uri = os.environ["TIKTOK_REDIRECT_URI"]
        return settings

    def save_configuration(
        self,
        client_key: str,
        client_secret: str,
        redirect_uri: str,
        timezone_name: str,
        scopes: str = "user.info.basic,video.publish",
    ) -> AppSettings:
        settings = self.store.load_settings()
        settings.client_key = client_key.strip()
        settings.redirect_uri = redirect_uri.strip()
        settings.timezone = timezone_name.strip() or "UTC"
        settings.scopes = scopes.strip()
        self.store.save_settings(settings)
        if client_secret:
            self.store.set_secret(settings.client_key, "client_secret", client_secret)
        return settings

    def connect(self) -> CreatorInfo:
        settings = self.settings()
        secret = self.store.get_secret(settings.client_key, "client_secret")
        flow = OAuthDesktopFlow(
            settings.client_key,
            secret,
            settings.redirect_uri,
            settings.scopes,
            log=self.log,
        )
        token = flow.authorize()
        self._save_token(settings, token)
        self.log("TikTok authorization completed.")
        return self.creator_info()

    def disconnect(self, revoke: bool = True) -> None:
        settings = self.settings()
        access_token = self.store.get_secret(settings.client_key, "access_token")
        client_secret = self.store.get_secret(settings.client_key, "client_secret")
        if revoke and access_token and client_secret:
            OAuthDesktopFlow(
                settings.client_key,
                client_secret,
                settings.redirect_uri,
                settings.scopes,
                log=self.log,
            ).revoke(access_token)
        for name in ("access_token", "refresh_token"):
            self.store.delete_secret(settings.client_key, name)
        settings.open_id = ""
        settings.token_scope = ""
        settings.access_expires_at = ""
        settings.refresh_expires_at = ""
        self.store.save_settings(settings)

    def valid_access_token(self) -> str:
        settings = self.settings()
        access_token = self.store.get_secret(settings.client_key, "access_token")
        if not access_token:
            raise RuntimeError("No TikTok account is connected. Use the Connect button or --connect.")

        expiry = parse_utc(settings.access_expires_at)
        if expiry is None or expiry <= utc_now() + timedelta(minutes=5):
            refresh_token = self.store.get_secret(settings.client_key, "refresh_token")
            secret = self.store.get_secret(settings.client_key, "client_secret")
            if not refresh_token or not secret:
                # Environment-only tokens may not have refresh metadata.
                if os.environ.get("TIKTOK_ACCESS_TOKEN"):
                    return access_token
                raise RuntimeError("Access token has expired and no refresh token is available.")
            self.log("Refreshing TikTok access token…")
            flow = OAuthDesktopFlow(
                settings.client_key,
                secret,
                settings.redirect_uri,
                settings.scopes,
                log=self.log,
            )
            token = flow.refresh(refresh_token)
            self._save_token(settings, token)
            access_token = token.access_token
        return access_token

    def creator_info(self) -> CreatorInfo:
        return TikTokClient(self.valid_access_token(), log=self.log).creator_info()

    def publish(self, payload: dict, progress=None, wait: bool = False) -> dict:
        if not payload.get("consent"):
            raise ValueError("Explicit user consent is required before sending a video to TikTok.")
        client = TikTokClient(self.valid_access_token(), log=self.log)
        result = client.direct_post(
            Path(payload["video"]),
            str(payload.get("caption", "")),
            str(payload["privacy_level"]),
            disable_comment=bool(payload.get("disable_comment", False)),
            disable_duet=bool(payload.get("disable_duet", False)),
            disable_stitch=bool(payload.get("disable_stitch", False)),
            brand_content_toggle=bool(payload.get("brand_content_toggle", False)),
            brand_organic_toggle=bool(payload.get("brand_organic_toggle", False)),
            is_aigc=bool(payload.get("is_aigc", False)),
            video_cover_timestamp_ms=payload.get("video_cover_timestamp_ms"),
            requested_chunk_size=int(payload.get("chunk_size", 16 * 1024 * 1024)),
            progress=progress,
        )
        if wait:
            result["post_status"] = client.wait_for_post(result["publish_id"])
        return result

    def schedule(self, scheduled_at: datetime, payload: dict) -> dict:
        if not payload.get("consent"):
            raise ValueError("Explicit user consent is required before scheduling a post.")
        job_id = self.queue.add(scheduled_at, payload)
        return {
            "status": "scheduled",
            "job_id": job_id,
            "scheduled_for": scheduled_at.isoformat(),
            "message": "Stored in the local queue. TikTok does not provide native scheduling for this endpoint.",
        }

    def run_due(self, wait: bool = False) -> list[dict]:
        results: list[dict] = []
        for job in self.queue.due():
            job_id = int(job["id"])
            self.queue.update(job_id, status="publishing")
            try:
                result = self.publish(job["payload"], wait=wait)
                self.queue.update(job_id, status="processing", publish_id=result.get("publish_id", ""))
                results.append({"job_id": job_id, **result})
            except Exception as exc:
                self.queue.update(job_id, status="retry", last_error=str(exc))
                results.append({"job_id": job_id, "status": "failed", "error": str(exc)})
        return results

    def fetch_status(self, publish_id: str) -> dict:
        return TikTokClient(self.valid_access_token(), log=self.log).fetch_post_status(publish_id)

    def _save_token(self, settings: AppSettings, token: TokenResponse) -> None:
        now = utc_now()
        self.store.set_secret(settings.client_key, "access_token", token.access_token)
        self.store.set_secret(settings.client_key, "refresh_token", token.refresh_token)
        settings.open_id = token.open_id
        settings.token_scope = token.scope
        settings.access_expires_at = (now + timedelta(seconds=token.expires_in)).isoformat()
        settings.refresh_expires_at = (now + timedelta(seconds=token.refresh_expires_in)).isoformat()
        self.store.save_settings(settings)
