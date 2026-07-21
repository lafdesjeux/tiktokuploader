#!/usr/bin/env python3
"""Compatibility entry point for automation scripts."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tiktok_desktop_publisher.cli import main  # noqa: E402

raise SystemExit(main())
