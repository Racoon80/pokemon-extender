"""The model files the app uses (6–9 GB, by GPU size). Downloaded once on the first start into HF_HOME.

The T5 text encoder (6.3 GB) is not part of it: the embeddings of the fixed default prompt ship
with the app (app/assets/prompt_embeds.safetensors). T5 is only fetched if someone sends their own
prompt through the API.

FLUX.1 Fill dev is gated: HF_TOKEN must belong to a Hugging Face account that accepted its licence.
Once everything is cached, nothing is fetched again and the token is no longer needed.
"""
from __future__ import annotations

import os
from typing import Callable

from huggingface_hub import hf_hub_download, snapshot_download

FLUX_REPO = os.environ.get("FLUX_MODEL", "black-forest-labs/FLUX.1-Fill-dev")
GGUF_REPO = os.environ.get("FLUX_GGUF_REPO", "YarvixPA/FLUX.1-Fill-dev-GGUF")


def gpu_total_gb() -> float:
    """VRAM of the first GPU, or VRAM_LIMIT_GB when set lower (shared GPU, or testing a smaller card)."""
    import torch
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    limit = float(os.environ.get("VRAM_LIMIT_GB", "0") or 0)
    return min(total, limit) if limit > 0 else total


def gguf_file() -> str:
    """FLUX_GGUF_FILE, or with "auto" the largest transformer that fits the card next to its work memory."""
    name = os.environ.get("FLUX_GGUF_FILE", "auto").strip()
    if name and name != "auto":
        return name
    if gpu_total_gb() >= 11:
        return "flux1-fill-dev-Q5_K_S.gguf"   # 8.3 GB
    return "flux1-fill-dev-Q3_K_S.gguf"       # 5.2 GB, small cards (from 6 GB)


T5_REPO = os.environ.get("FLUX_T5_REPO", "diffusers/FLUX.1-dev-bnb-4bit")

# Only the small parts of the original repo; it also holds a 24 GB transformer and a 9.5 GB T5.
BASE_PATTERNS = ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "tokenizer_2/*",
                 "vae/*", "transformer/config.json"]


def _cached_first(fetch: Callable[..., str]) -> str:
    """Use the local copy when there is one, so a finished download never needs the network again."""
    try:
        return fetch(local_files_only=True)
    except Exception:
        return fetch(local_files_only=False)


def base_dir() -> str:
    return _cached_first(lambda **kw: snapshot_download(FLUX_REPO, allow_patterns=BASE_PATTERNS, **kw))


def gguf_path() -> str:
    return _cached_first(lambda **kw: hf_hub_download(GGUF_REPO, gguf_file(), **kw))


def t5_dir() -> str:
    return _cached_first(lambda **kw: snapshot_download(T5_REPO, allow_patterns=["text_encoder_2/*"], **kw))


PARTS = (("FLUX Fill base", base_dir), ("FLUX Fill transformer", gguf_path))


def is_cached() -> bool:
    try:
        snapshot_download(FLUX_REPO, allow_patterns=BASE_PATTERNS, local_files_only=True)
        hf_hub_download(GGUF_REPO, gguf_file(), local_files_only=True)
        return True
    except Exception:
        return False


def fetch_all(on_part: Callable[[int, int, str], None] = lambda i, n, name: None) -> None:
    for i, (name, fetch) in enumerate(PARTS, 1):
        on_part(i, len(PARTS), name)
        fetch()


if __name__ == "__main__":
    fetch_all(lambda i, n, name: print(f"[{i}/{n}] {name}", flush=True))
    print("Models ready.")
