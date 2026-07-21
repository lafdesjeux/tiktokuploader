from __future__ import annotations

import json
import math
import mimetypes
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

BASE_URL = "https://open.tiktokapis.com"
MIN_CHUNK = 5 * 1024 * 1024
MAX_CHUNK = 64 * 1024 * 1024
MAX_FINAL_CHUNK = 128 * 1024 * 1024
MAX_CHUNK_COUNT = 1000


class TikTokAPIError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ChunkPlan:
    video_size: int
    chunk_size: int
    total_chunk_count: int
    chunk_lengths: tuple[int, ...]


@dataclass
class CreatorInfo:
    creator_username: str
    creator_nickname: str
    creator_avatar_url: str
    privacy_level_options: list[str]
    comment_disabled: bool
    duet_disabled: bool
    stitch_disabled: bool
    max_video_post_duration_sec: int

    @classmethod
    def from_payload(cls, payload: dict) -> "CreatorInfo":
        return cls(
            creator_username=str(payload.get("creator_username", "")),
            creator_nickname=str(payload.get("creator_nickname", "")),
            creator_avatar_url=str(payload.get("creator_avatar_url", "")),
            privacy_level_options=[str(item).strip() for item in payload.get("privacy_level_options", [])],
            comment_disabled=bool(payload.get("comment_disabled", False)),
            duet_disabled=bool(payload.get("duet_disabled", False)),
            stitch_disabled=bool(payload.get("stitch_disabled", False)),
            max_video_post_duration_sec=int(payload.get("max_video_post_duration_sec", 0)),
        )


def utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def build_chunk_plan(video_size: int, requested_chunk_size: int = 16 * 1024 * 1024) -> ChunkPlan:
    if video_size <= 0:
        raise ValueError("Video file is empty.")

    if video_size <= MAX_CHUNK:
        return ChunkPlan(video_size, video_size, 1, (video_size,))

    chunk_size = max(MIN_CHUNK, min(requested_chunk_size, MAX_CHUNK))
    minimum_for_count = math.ceil(video_size / MAX_CHUNK_COUNT)
    chunk_size = max(chunk_size, minimum_for_count)
    chunk_size = min(chunk_size, MAX_CHUNK)

    # TikTok defines total_chunk_count as floor(video_size / chunk_size) and
    # requires trailing bytes to be merged into the final chunk.
    total = video_size // chunk_size
    if total < 2:
        chunk_size = max(MIN_CHUNK, video_size // 2)
        total = video_size // chunk_size
    if total > MAX_CHUNK_COUNT:
        raise ValueError("Video requires more than 1000 chunks.")

    lengths = [chunk_size] * int(total)
    remainder = video_size - (chunk_size * int(total))
    if remainder:
        lengths[-1] += remainder
    if lengths[-1] > MAX_FINAL_CHUNK:
        raise ValueError("Final chunk exceeds TikTok's 128 MB limit.")
    return ChunkPlan(video_size, chunk_size, int(total), tuple(lengths))


def detect_video_duration(video: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


class TikTokClient:
    def __init__(
        self,
        access_token: str,
        base_url: str = BASE_URL,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")
        self.log = log or (lambda _message: None)

    def creator_info(self) -> CreatorInfo:
        payload = self._post_json("/v2/post/publish/creator_info/query/", {})
        return CreatorInfo.from_payload(payload.get("data", {}))

    def direct_post(
        self,
        video: Path,
        caption: str,
        privacy_level: str,
        *,
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
        brand_content_toggle: bool = False,
        brand_organic_toggle: bool = False,
        is_aigc: bool = False,
        video_cover_timestamp_ms: int | None = None,
        requested_chunk_size: int = 16 * 1024 * 1024,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        video = video.expanduser().resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        if utf16_length(caption) > 2200:
            raise ValueError("Caption exceeds TikTok's 2200 UTF-16 unit limit.")

        creator = self.creator_info()
        if privacy_level not in creator.privacy_level_options:
            raise TikTokAPIError(
                f"Privacy level {privacy_level!r} is not available for this account. "
                f"Available values: {', '.join(creator.privacy_level_options)}",
                code="privacy_level_option_mismatch",
            )

        duration = detect_video_duration(video)
        if duration is not None and creator.max_video_post_duration_sec:
            if duration > creator.max_video_post_duration_sec:
                raise ValueError(
                    f"Video duration is {duration:.1f}s, but this account allows "
                    f"{creator.max_video_post_duration_sec}s maximum."
                )

        disable_comment = disable_comment or creator.comment_disabled
        disable_duet = disable_duet or creator.duet_disabled
        disable_stitch = disable_stitch or creator.stitch_disabled
        plan = build_chunk_plan(video.stat().st_size, requested_chunk_size)

        post_info: dict[str, object] = {
            "title": caption,
            "privacy_level": privacy_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
            "brand_content_toggle": brand_content_toggle,
            "brand_organic_toggle": brand_organic_toggle,
            "is_aigc": is_aigc,
        }
        if video_cover_timestamp_ms is not None:
            post_info["video_cover_timestamp_ms"] = max(0, int(video_cover_timestamp_ms))

        payload = {
            "post_info": post_info,
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": plan.video_size,
                "chunk_size": plan.chunk_size,
                "total_chunk_count": plan.total_chunk_count,
            },
        }
        self.log("Initializing TikTok Direct Post…")
        response = self._post_json("/v2/post/publish/video/init/", payload)
        data = response.get("data", {})
        upload_url = data.get("upload_url")
        publish_id = str(data.get("publish_id", ""))
        if not upload_url or not publish_id:
            raise TikTokAPIError("TikTok did not return upload_url and publish_id.")

        self._upload(video, str(upload_url), plan, progress)
        return {
            "status": "processing",
            "publish_id": publish_id,
            "creator_username": creator.creator_username,
            "creator_nickname": creator.creator_nickname,
            "privacy_level": privacy_level,
        }

    def fetch_post_status(self, publish_id: str) -> dict:
        payload = self._post_json(
            "/v2/post/publish/status/fetch/",
            {"publish_id": publish_id},
        )
        return payload.get("data", {})

    def wait_for_post(
        self,
        publish_id: str,
        timeout_seconds: int = 180,
        interval_seconds: int = 5,
    ) -> dict:
        deadline = time.monotonic() + timeout_seconds
        last: dict = {}
        terminal = {"PUBLISH_COMPLETE", "FAILED", "SEND_TO_USER_INBOX"}
        while time.monotonic() < deadline:
            last = self.fetch_post_status(publish_id)
            status = str(last.get("status", ""))
            self.log(f"TikTok status: {status or 'unknown'}")
            if status in terminal:
                return last
            time.sleep(interval_seconds)
        return last | {"timed_out": True}

    def _upload(
        self,
        video: Path,
        upload_url: str,
        plan: ChunkPlan,
        progress: Callable[[int, int], None] | None,
    ) -> None:
        guessed, _ = mimetypes.guess_type(video.name)
        mime_type = guessed if guessed in {"video/mp4", "video/quicktime", "video/webm"} else "video/mp4"
        sent = 0
        with video.open("rb") as source:
            for index, length in enumerate(plan.chunk_lengths):
                body = source.read(length)
                if len(body) != length:
                    raise OSError(f"Unexpected end of file while reading chunk {index + 1}.")
                start = sent
                end = sent + length - 1
                self.log(
                    f"Uploading chunk {index + 1}/{plan.total_chunk_count} "
                    f"({start}-{end})…"
                )
                response = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": mime_type,
                        "Content-Length": str(length),
                        "Content-Range": f"bytes {start}-{end}/{plan.video_size}",
                    },
                    data=body,
                    timeout=600,
                )
                if response.status_code not in {200, 201, 206}:
                    raise TikTokAPIError(
                        f"TikTok upload failed: HTTP {response.status_code} {response.text}",
                        status_code=response.status_code,
                    )
                sent += length
                if progress:
                    progress(sent, plan.video_size)
        if sent != plan.video_size:
            raise OSError(f"Uploaded {sent} bytes but expected {plan.video_size}.")

    def _post_json(self, path: str, body: dict) -> dict:
        response = requests.post(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=body,
            timeout=120,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikTokAPIError(
                f"TikTok returned invalid JSON: HTTP {response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            ) from exc
        error = payload.get("error", {})
        code = str(error.get("code", ""))
        if response.status_code >= 400 or (code and code != "ok"):
            message = error.get("message") or payload.get("message") or json.dumps(payload)
            raise TikTokAPIError(
                f"TikTok API error {code or response.status_code}: {message}",
                code=code,
                status_code=response.status_code,
            )
        return payload
