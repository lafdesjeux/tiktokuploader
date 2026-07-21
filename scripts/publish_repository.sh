#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_URL="${1:-https://github.com/lafdesjeux/RetroReelsUploader.git}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="${2:-$HOME/Documents/GitHub/RetroReelsUploader}"

if [[ -d "$WORK_DIR/.git" ]]; then
  git -C "$WORK_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$WORK_DIR")"
  git clone "$REPOSITORY_URL" "$WORK_DIR"
fi

rsync -a --delete \
  --exclude '.git/' \
  --exclude 'tiktok*.txt' \
  "$SOURCE_DIR/" "$WORK_DIR/"

git -C "$WORK_DIR" add -A
git -C "$WORK_DIR" status --short

git -C "$WORK_DIR" commit -m "Add reusable TikTok desktop publisher" || true
git -C "$WORK_DIR" push
