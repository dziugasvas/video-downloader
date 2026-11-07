"""Small helpers that talk to the Mac: Finder, folder picker, tool checks, updates."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

IS_MAC = sys.platform == "darwin"


def ytdlp_version() -> str | None:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def tool_status() -> dict:
    return {
        "yt_dlp": ytdlp_version(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        # yt-dlp needs a JavaScript runtime (Deno) for full YouTube support.
        "deno": shutil.which("deno") is not None,
        "mac": IS_MAC,
    }


def update_ytdlp() -> tuple[bool, str]:
    """Upgrade yt-dlp inside this app's Python environment."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp[default]"],
        capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()[-1000:]


def reveal_in_finder(path: str) -> None:
    if IS_MAC:
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)


def open_folder(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    subprocess.run(["open" if IS_MAC else "xdg-open", path], check=False)


def choose_folder(start: str | None = None) -> str | None:
    """Show the native macOS folder picker. Returns None if cancelled."""
    if not IS_MAC:
        raise RuntimeError("The folder picker is only available on macOS.")
    script = ['activate']
    if start and os.path.isdir(start):
        script.append(
            'set f to choose folder with prompt "Save downloads to:" '
            f'default location (POSIX file {_applescript_str(start)})'
        )
    else:
        script.append('set f to choose folder with prompt "Save downloads to:"')
    script.append("return POSIX path of f")
    args = ["osascript"]
    for line in script:
        args += ["-e", line]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return None  # user pressed Cancel
    path = proc.stdout.strip()
    return path.rstrip("/") or "/"


def _applescript_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
