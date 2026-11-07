"""FastAPI routes for the downloader.

Use in any FastAPI app:

    from downloader import DownloadManager, create_router
    manager = DownloadManager(max_parallel=2)
    app.include_router(create_router(manager), prefix="/api/downloader")
"""

from __future__ import annotations

import os
import re

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from . import system
from .formats import QUALITIES
from .jobs import DEFAULT_FOLDER, DownloadManager


class DownloadRequest(BaseModel):
    urls: str  # one or more links, separated by spaces or new lines
    quality: str = "1080"
    folder: str | None = None


class PathRequest(BaseModel):
    path: str


def split_links(text: str) -> tuple[list[str], list[str]]:
    links, skipped = [], []
    for part in re.split(r"\s+", text.strip()):
        if not part:
            continue
        if re.match(r"^https?://\S+$", part):
            if part not in links:
                links.append(part)
        else:
            skipped.append(part)
    return links, skipped


def clean_folder(folder: str | None) -> str:
    path = os.path.abspath(os.path.expanduser((folder or "").strip() or DEFAULT_FOLDER))
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        raise HTTPException(400, f"Can't use this folder: {exc.strerror}") from exc
    if not os.access(path, os.W_OK):
        raise HTTPException(400, "This folder isn't writable.")
    return path


def create_router(manager: DownloadManager) -> APIRouter:
    router = APIRouter()

    @router.get("/status")
    async def status():
        info = await run_in_threadpool(system.tool_status)
        return {
            **info,
            "default_folder": DEFAULT_FOLDER,
            "qualities": [{"id": k, "label": v} for k, v in QUALITIES.items()],
        }

    @router.get("/downloads")
    def list_downloads():
        return {"jobs": manager.jobs(), "history": manager.history()}

    @router.post("/downloads")
    def add_downloads(req: DownloadRequest):
        if req.quality not in QUALITIES:
            raise HTTPException(400, "Unknown quality.")
        links, skipped = split_links(req.urls)
        if not links:
            raise HTTPException(400, "Paste at least one link (starting with https://).")
        folder = clean_folder(req.folder)
        jobs = [manager.add(url, req.quality, folder).public() for url in links]
        return {"jobs": jobs, "skipped": skipped}

    @router.post("/downloads/{job_id}/cancel")
    def cancel(job_id: str):
        if not manager.cancel(job_id):
            raise HTTPException(404, "Nothing to cancel.")
        return {"ok": True}

    @router.delete("/downloads/{job_id}")
    def remove(job_id: str):
        if not manager.remove(job_id):
            raise HTTPException(400, "Can't remove a download that's still running.")
        return {"ok": True}

    @router.post("/downloads/clear")
    def clear_finished():
        manager.clear_finished()
        return {"ok": True}

    @router.post("/history/clear")
    def clear_history():
        manager.clear_history()
        return {"ok": True}

    @router.post("/reveal")
    def reveal(req: PathRequest):
        if not manager.known_file(req.path):
            raise HTTPException(404, "Unknown file.")
        if not os.path.exists(req.path):
            raise HTTPException(404, "The file was moved or deleted.")
        system.reveal_in_finder(req.path)
        return {"ok": True}

    @router.post("/open-folder")
    def open_folder(req: PathRequest):
        system.open_folder(clean_folder(req.path))
        return {"ok": True}

    @router.post("/choose-folder")
    async def choose_folder(req: PathRequest):
        try:
            path = await run_in_threadpool(system.choose_folder, os.path.expanduser(req.path))
        except RuntimeError as exc:
            raise HTTPException(501, str(exc)) from exc
        return {"path": path}

    @router.post("/update-ytdlp")
    async def update_ytdlp():
        ok, output = await run_in_threadpool(system.update_ytdlp)
        version = await run_in_threadpool(system.ytdlp_version)
        if not ok:
            raise HTTPException(500, f"Update failed: {output}")
        return {"version": version}

    return router
