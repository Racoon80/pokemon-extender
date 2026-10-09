"""Web UI + API. A job takes a second or two, so the answer comes straight back.

Errors are returned as {"code": ..., **params} and translated by the UI (EN/DE/FR/LB)."""
from __future__ import annotations

import io
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from .layout import list_layouts, load_layout
from .pipeline import CardNotFound, Options, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extender")

OUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/data/outputs"))
STATIC = Path(__file__).parent / "static"
FILES = {"print.png", "print.pdf", "preview.jpg", "meta.json", "cut.dxf", "print-cut.svg", "cutout.svg"}
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
MAX_PIXELS = 40_000_000          # a phone photo is ~12 MP; refuses decompression bombs before decoding
MAX_JOBS = int(os.environ.get("MAX_JOBS", "2"))   # pictures processed at once; each can take a few hundred MB
OUTPUT_TTL = float(os.environ.get("OUTPUT_TTL_HOURS", "72")) * 3600
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

app = FastAPI(title="Pokemon Extender")
slots = threading.BoundedSemaphore(MAX_JOBS)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    return {"templates": {n: load_layout(n).name for n in list_layouts()}, "default_template": "psa"}


def _prune() -> None:
    """Delete results after OUTPUT_TTL."""
    cutoff = time.time() - OUTPUT_TTL
    if OUT_DIR.is_dir():
        for d in OUT_DIR.iterdir():
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


@app.post("/api/cut")
def cut(
    file: UploadFile = File(...),
    template: str = Form("psa"),
    bleed_mm: float = Form(2.0),
    dpi: int = Form(260),
):
    if template not in list_layouts():
        raise HTTPException(400, {"code": "unknown_option"})
    if not (72 <= dpi <= 600 and 0 <= bleed_mm <= 10):
        raise HTTPException(400, {"code": "out_of_range"})
    if not slots.acquire(timeout=30):
        raise HTTPException(429, {"code": "queue_full"})
    try:
        return _cut(file, Options(template=template, bleed_mm=bleed_mm, dpi=dpi))
    finally:
        slots.release()


def _cut(file: UploadFile, opts: Options) -> dict:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"code": "too_large", "max": MAX_UPLOAD_BYTES // 1024 // 1024})
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise ValueError
        img.load()
    except Exception:
        raise HTTPException(400, {"code": "not_image"})
    _prune()
    job_id = uuid.uuid4().hex[:12]
    try:
        meta = run(img, opts, OUT_DIR / job_id)
    except CardNotFound:
        shutil.rmtree(OUT_DIR / job_id, ignore_errors=True)
        raise HTTPException(422, {"code": "no_card"})
    return {"id": job_id, "meta": meta}


@app.get("/api/jobs/{job_id}/{name}")
def job_file(job_id: str, name: str):
    path = OUT_DIR / job_id / name
    if name not in FILES or not job_id.isalnum() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=f"slab-{job_id}-{name}")
