"""Video Downloader: a small local web app. Run with ./start.sh"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from downloader import DownloadManager, create_router

PORT = int(os.environ.get("VD_PORT", "8765"))
STATIC = Path(__file__).parent / "static"

manager = DownloadManager(max_parallel=2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    manager.shutdown()  # stop running downloads when the app quits


app = FastAPI(title="Video Downloader", lifespan=lifespan, docs_url=None, redoc_url=None)

ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Only answer this Mac's own browser tab: blocks other websites from
    sending requests to the app (DNS rebinding / cross-site requests)."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if host not in ALLOWED_HOSTS or (origin and origin.split("://", 1)[-1] not in ALLOWED_HOSTS):
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)


app.include_router(create_router(manager), prefix="/api")
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
