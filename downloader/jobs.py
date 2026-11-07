"""Download queue: runs yt-dlp, tracks progress, supports cancel, keeps history.

Each download runs yt-dlp as a separate process (``python -m yt_dlp``), so:
  * cancelling simply stops that process (and its ffmpeg),
  * an updated yt-dlp is picked up by the next download without a restart.

This module has no web code. It can be reused by any app.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import formats

DEFAULT_FOLDER = str(Path.home() / "Downloads" / "Videos")

# Output file names. Playlists get their own subfolder and numbered files.
OUTPUT_TEMPLATE = (
    "%(playlist_title|.)s/"
    "%(playlist_index&{:03d} - |)s"
    "%(title).150B.%(ext)s"
)

# Lines yt-dlp prints for us (see build_command); everything else is ignored
# apart from ERROR lines.
_TAGS = ("VD_ITEM ", "VD_SIZES ", "VD_PROG ", "VD_POST ", "VD_FILE ")

ACTIVE = ("queued", "starting", "downloading", "processing")

TEMP_DIR = ".video-downloader-temp"  # hidden, inside the download folder


@dataclass
class Job:
    id: str
    url: str
    format: str
    quality: str
    folder: str
    status: str = "queued"  # queued|starting|downloading|processing|done|error|cancelled
    title: str = ""
    percent: float = 0.0
    speed: float | None = None  # bytes/second
    eta: int | None = None  # seconds
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    item_index: int | None = None  # position inside a playlist
    item_count: int | None = None
    files: list[str] = field(default_factory=list)
    error: str = ""
    failed_items: int = 0
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def public(self) -> dict:
        data = asdict(self)
        data["label"] = formats.label(self.format, self.quality)
        return data


def build_command(url: str, fmt: str, quality: str, folder: str, temp: str) -> list[str]:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--newline", "--progress", "--no-simulate", "--no-colors",
        *formats.ytdlp_args(fmt, quality),
        "-P", folder, "-o", OUTPUT_TEMPLATE,
        # Unfinished pieces go to a private temp folder per download, so two
        # downloads of the same video never get in each other's way.
        "-P", f"temp:{temp}",
        # A link to a video that's inside a playlist downloads just that video;
        # a playlist link (youtube.com/playlist?list=...) downloads the playlist.
        "--no-playlist",
        # Set the file date to "now" so new downloads sort to the top in Finder.
        "--no-mtime",
        "--print", "before_dl:VD_ITEM %(.{id,title,playlist_index,n_entries,playlist_count})j",
        "--print", "before_dl:VD_SIZES %(requested_formats.:.{format_id,filesize,filesize_approx})j",
        "--print", "after_move:VD_FILE %(filepath)j",
        "--progress-template",
        "download:VD_PROG %(progress.{status,downloaded_bytes,total_bytes,total_bytes_estimate,speed,eta,filename})j",
        "--progress-template", "postprocess:VD_POST %(progress.{status,postprocessor})j",
    ]
    cmd += ["--", url]
    return cmd


class _Run:
    """Progress of the item (video) currently being downloaded.

    A YouTube video is usually two streams (video + audio) downloaded one after
    the other. Each progress line is matched to its stream by the format id in
    the file name (e.g. "Title.f137.mp4"), so the overall percentage and the
    byte counts always agree.
    """

    def __init__(self) -> None:
        self.parts: list[dict] = []  # {"id", "size"} from VD_SIZES
        self.done: dict[int, float] = {}  # part index -> downloaded bytes
        self.total: dict[int, float] = {}  # part index -> total bytes
        self.part_files: list[str] = []

    def new_item(self, sizes=None) -> None:
        self.parts = []
        if isinstance(sizes, list):
            for s in sizes:
                s = s or {}
                size = s.get("filesize") or s.get("filesize_approx")
                self.parts.append({"id": str(s.get("format_id") or ""), "size": float(size) if size else None})
        self.done, self.total, self.part_files = {}, {}, []

    def _index(self, filename: str) -> int:
        m = re.search(r"\.f([^.]+)\.\w+(?:\.part)?$", filename or "")
        if m:
            for i, part in enumerate(self.parts):
                if part["id"] == m.group(1):
                    return i
        return 0

    def update(self, filename: str | None, downloaded: float, total: float | None, finished: bool) -> None:
        if filename and filename not in self.part_files:
            self.part_files.append(filename)
        i = self._index(filename or "")
        if total:
            self.total[i] = float(total)
        if finished and i in self.total:
            downloaded = self.total[i]
        self.done[i] = float(downloaded)

    def _sizes(self) -> list[float | None]:
        n = max(len(self.parts), (max(self.total) + 1) if self.total else 1)
        out = []
        for i in range(n):
            known = self.total.get(i) or (self.parts[i]["size"] if i < len(self.parts) else None)
            out.append(known)
        return out

    def fraction(self) -> float:
        sizes = self._sizes()
        if all(sizes):
            return min(sum(self.done.values()) / sum(sizes), 1.0)
        # Sizes unknown: count each stream equally.
        fracs = [min(self.done.get(i, 0) / s, 1.0) if s else 0.0 for i, s in enumerate(sizes)]
        return sum(fracs) / len(fracs)

    def bytes(self) -> tuple[int, int | None]:
        sizes = self._sizes()
        return int(sum(self.done.values())), (int(sum(sizes)) if all(sizes) else None)

    def last_part_finished(self) -> bool:
        sizes = self._sizes()
        return all(s and self.done.get(i, 0) >= s for i, s in enumerate(sizes))


class DownloadManager:
    def __init__(self, max_parallel: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._history: list[dict] = []  # in memory only, cleared on restart
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="download")

    # ---- public API -----------------------------------------------------

    def add(self, url: str, fmt: str, quality: str, folder: str | None = None) -> Job:
        formats.validate(fmt, quality)
        url = url.strip()
        if not re.match(r"^https?://", url):
            raise ValueError(f"Not a link: {url}")
        folder = os.path.abspath(os.path.expanduser(folder or DEFAULT_FOLDER))
        job = Job(id=uuid.uuid4().hex[:10], url=url, format=fmt, quality=quality, folder=folder)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job.id)
        return job

    def jobs(self) -> list[dict]:
        with self._lock:
            return [j.public() for j in sorted(self._jobs.values(), key=lambda j: -j.created)]

    def history(self) -> list[dict]:
        with self._lock:
            return list(reversed(self._history))

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ACTIVE:
                return False
            job.status = "cancelled"
            job.finished = time.time()
            proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # yt-dlp and its ffmpeg
            except (ProcessLookupError, PermissionError):
                pass
        return True

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in ACTIVE:
                return False
            del self._jobs[job_id]
            return True

    def clear_finished(self) -> None:
        with self._lock:
            for jid in [j.id for j in self._jobs.values() if j.status not in ACTIVE]:
                del self._jobs[jid]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()

    def known_file(self, path: str) -> bool:
        """True if the path is a file this app downloaded (used by "Show in Finder")."""
        with self._lock:
            return any(h["path"] == path for h in self._history) or any(
                path in j.files for j in self._jobs.values()
            )

    def shutdown(self) -> None:
        for jid in list(self._procs):
            self.cancel(jid)
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---- worker ---------------------------------------------------------

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status != "queued":
                return  # cancelled or removed while waiting
            job.status = "starting"
        try:
            os.makedirs(job.folder, exist_ok=True)
            temp = os.path.join(job.folder, TEMP_DIR, job.id)
            proc = subprocess.Popen(
                build_command(job.url, job.format, job.quality, job.folder, temp),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, bufsize=1,
                start_new_session=True,  # own process group, so cancel stops ffmpeg too
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except Exception as exc:  # e.g. folder not writable
            self._finish(job_id, "error", str(exc))
            return

        with self._lock:
            self._procs[job_id] = proc
        run = _Run()
        last_error = ""
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("ERROR:"):
                last_error = _clean_error(line)
                with self._lock:
                    if job.item_count:
                        job.failed_items += 1
                continue
            if not line.startswith(_TAGS):
                continue
            tag, _, payload = line.partition(" ")
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            self._handle(job, run, tag, data)

        proc.wait()
        _remove_temp(job.folder, temp)  # leftovers of a cancelled or failed download
        with self._lock:
            self._procs.pop(job_id, None)
            cancelled = job.status == "cancelled"
        if cancelled:
            return
        if job.files and (proc.returncode == 0 or job.item_count):
            msg = ""
            if job.failed_items:
                msg = f"{job.failed_items} item(s) could not be downloaded. Last error: {last_error}"
            self._finish(job_id, "done", msg)
        elif proc.returncode == 0:
            self._finish(job_id, "error", "Nothing was downloaded (empty playlist?)")
        else:
            self._finish(job_id, "error", last_error or f"yt-dlp exited with code {proc.returncode}")

    def _handle(self, job: Job, run: _Run, tag: str, data) -> None:
        with self._lock:
            if job.status == "cancelled":
                return
            if tag == "VD_ITEM" and isinstance(data, dict):
                job.title = data.get("title") or job.title
                count = data.get("n_entries") or data.get("playlist_count")
                if data.get("playlist_index") and count:
                    job.item_index, job.item_count = int(data["playlist_index"]), int(count)
                job.status = "downloading"
                job.percent = _overall(job, 0.0)
                run.new_item(None)
            elif tag == "VD_SIZES":
                run.new_item(data)
            elif tag == "VD_PROG" and isinstance(data, dict):
                finished = data.get("status") == "finished"
                run.update(
                    data.get("filename"),
                    data.get("downloaded_bytes") or 0,
                    data.get("total_bytes") or data.get("total_bytes_estimate"),
                    finished,
                )
                done, total = run.bytes()
                speed = data.get("speed")
                job.status = "downloading"
                job.downloaded_bytes, job.total_bytes, job.speed = done, total, speed
                if total and speed:
                    job.eta = int(max(total - done, 0) / speed)  # time left for the whole video
                else:
                    job.eta = int(data["eta"]) if data.get("eta") is not None else None
                job.percent = _overall(job, run.fraction())
                if finished and run.last_part_finished():
                    job.status, job.speed, job.eta = "processing", None, None
            elif tag == "VD_POST" and isinstance(data, dict):
                if data.get("status") == "started" and data.get("postprocessor") != "MoveFiles":
                    job.status, job.speed, job.eta = "processing", None, None
            elif tag == "VD_FILE" and isinstance(data, str):
                data = os.path.normpath(data)
                if data not in job.files:
                    job.files.append(data)
                    try:
                        size = os.path.getsize(data)
                    except OSError:
                        size = None
                    # Same file downloaded again: move it to the top instead of listing it twice.
                    self._history = [h for h in self._history if h["path"] != data]
                    self._history.append({
                        "title": job.title or os.path.basename(data),
                        "path": data,
                        "size": size,
                        "format": job.format,
                        "audio": formats.FORMATS[job.format]["audio_only"],
                        "label": formats.label(job.format, job.quality),
                        "finished": time.time(),
                    })
                job.percent = _overall(job, 1.0)

    def _finish(self, job_id: str, status: str, message: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status == "cancelled":
                return
            job.status, job.error, job.finished = status, message, time.time()
            job.speed = job.eta = None
            if status == "done":
                job.percent = 100.0


def _overall(job: Job, item_fraction: float) -> float:
    if job.item_index and job.item_count:
        return round(100 * (job.item_index - 1 + item_fraction) / job.item_count, 1)
    return round(100 * item_fraction, 1)


def _clean_error(line: str) -> str:
    msg = line[len("ERROR:"):].strip()
    msg = re.sub(r"^\[[\w:]+\]\s*[\w-]+:\s*", "", msg)  # drop "[youtube] abc123: "
    msg = re.split(r";\s*please report this issue", msg)[0]
    msg = re.sub(r"\s*\(caused by .*\)$", "", msg)
    return msg[:500]


def _remove_temp(folder: str, temp: str) -> None:
    shutil.rmtree(temp, ignore_errors=True)
    try:
        os.rmdir(os.path.join(folder, TEMP_DIR))  # only succeeds when empty
    except OSError:
        pass
