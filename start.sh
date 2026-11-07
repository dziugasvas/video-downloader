#!/bin/bash
# Starts Video Downloader and opens it in your browser.
# The first run sets everything up (takes a minute). Press Ctrl+C to quit.
set -e
cd "$(dirname "$0")"

# Make Homebrew tools (ffmpeg, deno, python) findable, even when double-clicked.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PORT="${VD_PORT:-8765}"
URL="http://127.0.0.1:$PORT"

# Already running? Just open it.
if curl -fsS -o /dev/null "$URL/api/downloads" 2>/dev/null; then
  echo "Video Downloader is already running: $URL"
  open "$URL"
  exit 0
fi

# Find Python 3.10 or newer.
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed. Install it with: brew install python@3.12"
  exit 1
fi

# First run (or requirements changed): create the app's own Python environment.
if [ ! -x .venv/bin/python ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "Setting up (first run takes a minute)..."
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet --upgrade -r requirements.txt
  touch .venv/.installed .venv/.ytdlp-updated
fi

# Keep yt-dlp fresh: update automatically if the last check was over a day ago.
if [ -z "$(find .venv/.ytdlp-updated -mtime -1 2>/dev/null)" ]; then
  echo "Checking for yt-dlp updates..."
  if .venv/bin/python -m pip install --quiet --upgrade "yt-dlp[default]"; then
    touch .venv/.ytdlp-updated
  else
    echo "(Couldn't update yt-dlp right now. Using the installed version.)"
  fi
fi

command -v ffmpeg >/dev/null 2>&1 || echo "WARNING: ffmpeg not found. Install it with: brew install ffmpeg"
command -v deno   >/dev/null 2>&1 || echo "WARNING: Deno not found (YouTube needs it). Install it with: brew install deno"

# Open the browser as soon as the server answers (the very first start can take ~20 s).
(
  for _ in $(seq 1 240); do
    if curl -fsS -o /dev/null "$URL/api/downloads" 2>/dev/null; then
      echo ""
      echo "Video Downloader is running at $URL"
      echo "Keep this window open while you use it. Press Ctrl+C to quit."
      echo ""
      open "$URL"
      exit 0
    fi
    sleep 0.25
  done
  echo "Still starting... if the browser doesn't open, go to $URL"
) &

echo "Starting Video Downloader (please wait)..."
exec .venv/bin/python main.py
