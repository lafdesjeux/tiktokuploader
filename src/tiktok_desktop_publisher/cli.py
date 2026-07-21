from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .service import PublisherService


def parse_local_datetime(value: str, timezone_name: str) -> datetime:
    value = value.strip()
    timezone = ZoneInfo(timezone_name)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone)
        except ValueError:
            pass
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generic desktop/CLI publisher for TikTok's Content Posting API."
    )
    parser.add_argument("--connect", action="store_true", help="Run the TikTok desktop OAuth flow.")
    parser.add_argument("--disconnect", action="store_true", help="Revoke and remove stored tokens.")
    parser.add_argument("--run-due", action="store_true", help="Publish locally queued jobs whose date is due.")
    parser.add_argument("--list-queue", action="store_true", help="Print the local publish queue.")
    parser.add_argument("--status", metavar="PUBLISH_ID", help="Fetch a TikTok publish status.")

    parser.add_argument("--client-key", default="")
    parser.add_argument("--client-secret", default="")
    parser.add_argument("--redirect-uri", default="")
    parser.add_argument("--timezone", default="")

    parser.add_argument("--video")
    parser.add_argument("--post", "--caption", dest="caption")
    parser.add_argument("--tiktok-date", "--publish-at", dest="publish_at", default="")
    parser.add_argument("--privacy-level", default="SELF_ONLY")
    parser.add_argument("--disable-comment", action="store_true")
    parser.add_argument("--disable-duet", action="store_true")
    parser.add_argument("--disable-stitch", action="store_true")
    parser.add_argument("--brand-content", action="store_true")
    parser.add_argument("--brand-organic", action="store_true")
    parser.add_argument("--ai-generated", action="store_true")
    parser.add_argument("--cover-ms", type=int)
    parser.add_argument("--consent", action="store_true", help="Confirm the user approved this export.")
    parser.add_argument("--wait", action="store_true", help="Poll TikTok after upload.")

    # Compatibility arguments accepted but not used by the generic publisher.
    parser.add_argument("--game")
    parser.add_argument("--platform")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = PublisherService(log=lambda message: print(message, file=sys.stderr))
    settings = service.settings()

    if args.client_key or args.client_secret or args.redirect_uri or args.timezone:
        settings = service.save_configuration(
            args.client_key or settings.client_key,
            args.client_secret,
            args.redirect_uri or settings.redirect_uri,
            args.timezone or settings.timezone,
            settings.scopes,
        )

    if args.connect:
        print(json.dumps(service.connect().__dict__, ensure_ascii=False, indent=2))
        return 0
    if args.disconnect:
        service.disconnect()
        print(json.dumps({"status": "disconnected"}))
        return 0
    if args.list_queue:
        print(json.dumps(service.queue.list(), ensure_ascii=False, indent=2))
        return 0
    if args.run_due:
        print(json.dumps(service.run_due(wait=args.wait), ensure_ascii=False, indent=2))
        return 0
    if args.status:
        print(json.dumps(service.fetch_status(args.status), ensure_ascii=False, indent=2))
        return 0

    if not args.video or args.caption is None:
        parser.error("--video and --post/--caption are required for publishing or scheduling")
    video = Path(args.video).expanduser()
    if not video.is_file():
        parser.error(f"video not found: {video}")

    payload = {
        "video": str(video.resolve()),
        "caption": args.caption,
        "privacy_level": args.privacy_level,
        "disable_comment": args.disable_comment,
        "disable_duet": args.disable_duet,
        "disable_stitch": args.disable_stitch,
        "brand_content_toggle": args.brand_content,
        "brand_organic_toggle": args.brand_organic,
        "is_aigc": args.ai_generated,
        "video_cover_timestamp_ms": args.cover_ms,
        "consent": args.consent,
    }

    date_value = args.publish_at.strip()
    if date_value.lower() not in {"", "none", "null"}:
        publish_at = parse_local_datetime(date_value, args.timezone or settings.timezone)
        if publish_at > datetime.now(publish_at.tzinfo):
            result = service.schedule(publish_at, payload)
        else:
            result = service.publish(payload, wait=args.wait)
    else:
        result = service.publish(payload, wait=args.wait)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
