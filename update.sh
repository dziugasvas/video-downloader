#!/bin/bash
# Updates yt-dlp (and the other tools) to the latest version.
# Run this whenever YouTube downloads stop working.
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -x .venv/bin/python ]; then
  echo "Run ./start.sh once first to set things up."
  exit 1
fi

echo "Updating yt-dlp..."
.venv/bin/python -m pip install --quiet --upgrade "yt-dlp[default]"
touch .venv/.ytdlp-updated
echo "yt-dlp version: $(.venv/bin/python -m yt_dlp --version)"

if command -v brew >/dev/null 2>&1; then
  echo "Updating ffmpeg and deno via Homebrew..."
  brew upgrade ffmpeg deno 2>/dev/null || true
fi
echo "Done."
