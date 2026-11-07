"""Video download module (yt-dlp + ffmpeg). Self-contained so it can be copied into another app."""

from .api import create_router
from .jobs import DEFAULT_FOLDER, DownloadManager

__all__ = ["DownloadManager", "create_router", "DEFAULT_FOLDER"]
