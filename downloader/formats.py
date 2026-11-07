"""Which streams yt-dlp should pick for each file format + quality.

MP4 uses H.264 video + AAC audio whenever the site offers it, so it plays on
everything: iPhone, Samsung/Android, Mac, Windows, TVs. YouTube has no H.264
above 1080p, so 1440p/4K MP4 uses AV1 (newer devices). VP9 is avoided in MP4
because Apple devices can't play it.
"""

from __future__ import annotations

FORMATS = {
    "mp4": {"label": "MP4", "audio_only": False},
    "mkv": {"label": "MKV", "audio_only": False},
    "mp3": {"label": "MP3", "audio_only": True},
    "m4a": {"label": "M4A", "audio_only": True},
}

QUALITIES = {
    "480": "480p",
    "720": "720p",
    "1080": "1080p",
    "1440": "1440p",
    "2160": "4K",
    "best": "Best",
}

# Video Apple and Android devices can both play, with AAC audio.
_MP4_VIDEO = "bv*[vcodec~='^(avc1|av01)']+ba[acodec^=mp4a]/bv*[vcodec~='^(avc1|av01)']+ba"


def label(fmt: str, quality: str) -> str:
    f = FORMATS[fmt]
    return f["label"] if f["audio_only"] else f'{f["label"]} · {QUALITIES[quality]}'


def validate(fmt: str, quality: str) -> None:
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format: {fmt}")
    if quality not in QUALITIES:
        raise ValueError(f"Unknown quality: {quality}")


def ytdlp_args(fmt: str, quality: str) -> list[str]:
    """yt-dlp command-line options for a format + quality."""
    validate(fmt, quality)
    res = "res" if quality == "best" else f"res:{quality}"

    if fmt == "mp4":
        return [
            "-f", f"{_MP4_VIDEO}/bv*+ba/b",
            "-S", f"{res},vcodec:h264,acodec:aac",
            "--merge-output-format", "mp4", "--remux-video", "mp4",
        ]
    if fmt == "mkv":
        # Best streams as they are (VP9/AV1 + Opus), no conversion. For VLC/computers.
        return [
            "-f", "bv*+ba/b",
            "-S", res,
            "--merge-output-format", "mkv", "--remux-video", "mkv",
        ]
    if fmt == "m4a":
        return [
            "-f", "ba[acodec^=mp4a]/ba/b", "-S", "acodec:aac",
            "-x", "--audio-format", "m4a", "--embed-metadata",
        ]
    if fmt == "mp3":
        return [
            "-f", "ba/b",
            "-x", "--audio-format", "mp3", "--audio-quality", "0", "--embed-metadata",
        ]
    raise ValueError(fmt)
