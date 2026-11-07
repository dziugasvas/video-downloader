"""Download queue: runs yt-dlp, tracks progress, supports cancel, keeps history.

Each download runs yt-dlp as a separate process (``python -m yt_dlp``), so:
  * cancelling simply stops that process (and its ffmpeg),
  * an updated yt-dlp is picked up by the next download without a restart.

This module has no web code. It can be reused by any app.
"""

from __future__ import annotations

import glob
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .formats import QUALITIES, format_options

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


@dataclass
class Job:
    id: str
    url: str
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
        data["quality_label"] = QUALITIES.get(self.quality, self.quality)
        return data


def build_command(url: str, quality: str, folder: str) -> list[str]:
    fmt, sort = format_options(quality)
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--newline", "--progress", "--no-simulate", "--no-colors",
        "-f", fmt, "-S", ",".join(sort),
        "-P", folder, "-o", OUTPUT_TEMPLATE,
        # A link to a video that's inside a playlist downloads just that video;
        # a playlist link (youtube.com/playlist?list=...) downloads the playlist.
        "--no-playlist",
        # Set the file date to "now" so new downloads sort to the top in Finder.
        "--no-mtime",
        "--print", "before_dl:VD_ITEM %(.{id,title,playlist_index,n_entries,playlist_count})j",
        "--print", "before_dl:VD_SIZES %(requested_formats.:.{filesize,filesize_approx})j",
        "--print", "after_move:VD_FILE %(filepath)j",
        "--progress-template",
        "download:VD_PROG %(progress.{status,downloaded_bytes,total_bytes,total_bytes_estimate,speed,eta,filename})j",
        "--progress-template", "postprocess:VD_POST %(progress.{status,postprocessor})j",
    ]
    if quality == "audio":
        cmd += ["-x", "--audio-format", "m4a", "--embed-metadata"]
    else:
        cmd += ["--merge-output-format", "mp4", "--remux-video", "mp4"]
    cmd += ["--", url]
    return cmd


class _Run:
    """Progress bookkeeping for the item currently being downloaded."""

    def __init__(self) -> None:
        self.part_weights: list[float] = [1.0]
        self.part = 0
        self.part_files: list[str] = []
        self.current_file: str | None = None

    def new_item(self, sizes) -> None:
        weights = []
        if isinstance(sizes, list) and sizes:
            for s in sizes:
                s = s or {}
                weights.append(float(s.get("filesize") or s.get("filesize_approx") or 0))
            if not all(weights):
                weights = [1.0] * len(sizes)
        self.part_weights = weights or [1.0]
        self.part = 0
        self.part_files = []
        self.current_file = None

    def fraction(self, part_fraction: float) -> float:
        total = sum(self.part_weights)
        i = min(self.part, len(self.part_weights) - 1)
        done = sum(self.part_weights[:i])
        return (done + self.part_weights[i] * part_fraction) / total


class DownloadManager:
    def __init__(self, max_parallel: int = 2) -> None:
        self._jobs: dict[str, Job] = {}
        self._history: list[dict] = []  # in memory only, cleared on restart
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="download")

    # ---- public API -----------------------------------------------------

    def add(self, url: str, quality: str, folder: str | None = None) -> Job:
        if quality not in QUALITIES:
            raise ValueError(f"Unknown quality: {quality}")
        url = url.strip()
        if not re.match(r"^https?://", url):
            raise ValueError(f"Not a link: {url}")
        folder = os.path.abspath(os.path.expanduser(folder or DEFAULT_FOLDER))
        job = Job(id=uuid.uuid4().hex[:10], url=url, quality=quality, folder=folder)
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
            proc = subprocess.Popen(
                build_command(job.url, job.quality, job.folder),
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
        with self._lock:
            self._procs.pop(job_id, None)
            cancelled = job.status == "cancelled"
        if cancelled:
            _remove_partial_files(run)
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
                fname = data.get("filename")
                if fname and fname != run.current_file:
                    if run.current_file is not None:
                        run.part += 1
                    run.current_file = fname
                    run.part_files.append(fname)
                done = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                frac = 1.0 if data.get("status") == "finished" else (min(done / total, 1.0) if total else 0.0)
                job.status = "downloading"
                job.downloaded_bytes, job.total_bytes = int(done), int(total) if total else None
                job.speed = data.get("speed")
                job.eta = int(data["eta"]) if data.get("eta") is not None else None
                job.percent = _overall(job, run.fraction(frac))
                if data.get("status") == "finished" and run.part >= len(run.part_weights) - 1:
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
                        "quality": job.quality,
                        "quality_label": QUALITIES.get(job.quality, job.quality),
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


def _remove_partial_files(run: _Run) -> None:
    """Delete leftovers of the item that was being downloaded when cancelled."""
    patterns = set()
    for f in run.part_files:
        esc = glob.escape(f)
        patterns.update({esc + ".part", esc + ".part-Frag*", esc + ".ytdl"})
        base, is_part = re.subn(r"\.f[\w-]+\.\w+$", "", f)
        if is_part:  # separate video/audio stream, never a finished file
            patterns.add(esc)
            patterns.add(glob.escape(base) + ".temp.*")
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                os.remove(path)
            except OSError:
                pass
