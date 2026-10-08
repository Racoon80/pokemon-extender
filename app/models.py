"""The model files the app uses (~15 GB). Downloaded once on the first start into HF_HOME (a volume).

FLUX.1 Fill dev is gated: HF_TOKEN must belong to a Hugging Face account that accepted its licence.
Once everything is cached, nothing is fetched again and the token is no longer needed.
"""
from __future__ import annotations

import os
from typing import Callable

from huggingface_hub import hf_hub_download, snapshot_download

FLUX_REPO = os.environ.get("FLUX_MODEL", "black-forest-labs/FLUX.1-Fill-dev")
GGUF_REPO = os.environ.get("FLUX_GGUF_REPO", "YarvixPA/FLUX.1-Fill-dev-GGUF")
GGUF_FILE = os.environ.get("FLUX_GGUF_FILE", "flux1-fill-dev-Q5_K_S.gguf")
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
    return _cached_first(lambda **kw: hf_hub_download(GGUF_REPO, GGUF_FILE, **kw))


def t5_dir() -> str:
    return _cached_first(lambda **kw: snapshot_download(T5_REPO, allow_patterns=["text_encoder_2/*"], **kw))


PARTS = (("FLUX Fill base", base_dir), (GGUF_FILE, gguf_path), ("T5 text encoder", t5_dir))


def is_cached() -> bool:
    try:
        snapshot_download(FLUX_REPO, allow_patterns=BASE_PATTERNS, local_files_only=True)
        hf_hub_download(GGUF_REPO, GGUF_FILE, local_files_only=True)
        snapshot_download(T5_REPO, allow_patterns=["text_encoder_2/*"], local_files_only=True)
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
