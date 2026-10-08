"""Web UI + API. One GPU job at a time; the browser polls for the result."""
from __future__ import annotations

import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from . import backends
from .layout import list_layouts, load_layout
from .pipeline import Options, run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extender")

OUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/data/outputs"))
DEFAULT_BACKEND = os.environ.get("DEFAULT_BACKEND", "flux")
STATIC = Path(__file__).parent / "static"
FILES = {"print.png", "print.pdf", "preview.jpg", "raw.png", "mask.png", "card.png", "meta.json"}

app = FastAPI(title="Pokemon Extender")
gpu = ThreadPoolExecutor(max_workers=1)
jobs: dict[str, dict] = {}


@app.on_event("startup")
def preload() -> None:
    if os.environ.get("PRELOAD", "1") == "1" and DEFAULT_BACKEND != "preview":
        gpu.submit(backends.get_backend, DEFAULT_BACKEND)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
def config():
    return {
        "templates": {n: load_layout(n).name for n in list_layouts()},
        "backends": backends.available(),
        "default_backend": DEFAULT_BACKEND,
        "default_prompt": backends.DEFAULT_PROMPT,
    }


def _work(job_id: str, img: Image.Image, opts: Options) -> None:
    jobs[job_id]["status"] = "running"
    try:
        jobs[job_id]["meta"] = run(img, opts, OUT_DIR / job_id)
        jobs[job_id]["status"] = "done"
    except Exception as e:  # surfaced to the UI
        log.exception("Job %s feelgeschloen", job_id)
        jobs[job_id].update(status="error", error=str(e))


@app.post("/api/extend")
async def extend(
    file: UploadFile = File(...),
    template: str = Form("psa"),
    backend: str = Form(DEFAULT_BACKEND),
    prompt: str = Form(""),
    seed: int = Form(-1),
    steps: int = Form(40),
    inset_mm: float = Form(2.5),
    bleed_mm: float = Form(0.0),
    dpi: int = Form(300),
    guides: bool = Form(False),
):
    try:
        img = Image.open(io.BytesIO(await file.read()))
        img.load()
    except Exception:
        raise HTTPException(400, "Dat ass kee Bild")
    if template not in list_layouts() or backend not in backends.available():
        raise HTTPException(400, "Onbekannt Schabloun oder Backend")
    if not (1 <= steps <= 100 and 72 <= dpi <= 1200 and 0 <= bleed_mm <= 10 and 0 <= inset_mm <= 10):
        raise HTTPException(400, "Wäert ausserhalb vum Beräich")
    opts = Options(template=template, backend=backend, prompt=prompt, seed=seed, steps=steps,
                   inset_mm=inset_mm, bleed_mm=bleed_mm, dpi=dpi, guides=guides)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued"}
    gpu.submit(_work, job_id, img, opts)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    return jobs[job_id]


@app.get("/api/jobs/{job_id}/{name}")
def job_file(job_id: str, name: str):
    path = OUT_DIR / job_id / name
    if name not in FILES or not job_id.isalnum() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=f"slab-{job_id}-{name}")
