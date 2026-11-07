"""yt-dlp format choices for each quality option.

Video files are mp4 with H.264 video and AAC audio wherever YouTube offers it,
so they play everywhere (QuickTime, iPhone, iPad). Above 1080p YouTube has no
H.264, so "best" may use AV1 (plays on Apple-silicon Macs and iPhone 15 Pro or
newer). VP9 is only used as a last resort because QuickTime can't play it.
"""

QUALITIES = {
    "720": "720p",
    "1080": "1080p",
    "best": "Best",
    "audio": "Audio only (m4a)",
}

# Video streams Apple devices can play, merged with AAC audio.
_APPLE_VIDEO = "bv*[vcodec~='^(avc1|av01)']+ba[acodec^=mp4a]"
_FALLBACK = "bv*+ba/b"


def format_options(quality: str) -> tuple[str, list[str]]:
    """Return (format selector, format sort keys) for a quality option."""
    if quality == "audio":
        return "ba[acodec^=mp4a]/ba/b", ["acodec:aac"]
    if quality in ("720", "1080"):
        return f"{_APPLE_VIDEO}/{_FALLBACK}", [f"res:{quality}", "vcodec:h264", "acodec:aac"]
    if quality == "best":
        return f"{_APPLE_VIDEO}/{_FALLBACK}", ["res", "vcodec:h264", "acodec:aac"]
    raise ValueError(f"Unknown quality: {quality}")
