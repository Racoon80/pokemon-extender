"""The model files the app uses. They are fetched once, while the Docker image is built.

`python -m app.models` downloads them into HF_HOME. The Dockerfile runs it with the Hugging Face
token mounted as a build secret (the .env file), so the token never ends up in the image, and the
running container works offline.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

FLUX_REPO = os.environ.get("FLUX_MODEL", "black-forest-labs/FLUX.1-Fill-dev")
GGUF_REPO = os.environ.get("FLUX_GGUF_REPO", "YarvixPA/FLUX.1-Fill-dev-GGUF")
GGUF_FILE = os.environ.get("FLUX_GGUF_FILE", "flux1-fill-dev-Q5_K_S.gguf")
T5_REPO = os.environ.get("FLUX_T5_REPO", "diffusers/FLUX.1-dev-bnb-4bit")

# Only the small parts of the original repo; it also holds a 24 GB transformer and a 9.5 GB T5.
BASE_PATTERNS = ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "tokenizer_2/*",
                 "vae/*", "transformer/config.json"]


def base_dir(token: str | None = None) -> str:
    return snapshot_download(FLUX_REPO, allow_patterns=BASE_PATTERNS, token=token)


def gguf_path(token: str | None = None) -> str:
    return hf_hub_download(GGUF_REPO, GGUF_FILE, token=token)


def t5_dir(token: str | None = None) -> str:
    return snapshot_download(T5_REPO, allow_patterns=["text_encoder_2/*"], token=token)


def _token_from(env_file: Path) -> str | None:
    if not env_file.is_file():
        return None
    for line in env_file.read_text().splitlines():
        key, _, value = line.strip().partition("=")
        if key == "HF_TOKEN" and value and not value.startswith("hf_..."):
            return value.strip().strip('"').strip("'")
    return None


def main() -> None:
    token = os.environ.get("HF_TOKEN") or _token_from(Path(sys.argv[1] if len(sys.argv) > 1 else "/run/secrets/hf_env"))
    if not token:
        sys.exit("No Hugging Face token. Put HF_TOKEN=... into .env (see .env.example) and build again.")
    for name, fetch in (("FLUX Fill base", base_dir), (f"transformer {GGUF_FILE}", gguf_path), ("T5 nf4", t5_dir)):
        print(f"Downloading {name} …", flush=True)
        try:
            fetch(token)
        except Exception as e:  # make the build fail with a readable reason
            sys.exit(f"Download of {name} failed: {e}\n"
                     f"Did you accept the licence at https://huggingface.co/{FLUX_REPO} ?")
    print("Models ready.", flush=True)


if __name__ == "__main__":
    main()
