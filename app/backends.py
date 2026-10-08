"""Outpainting engines. Each takes an init image + mask (white = paint) and returns an image of the same size."""
from __future__ import annotations

import logging
import os
import threading

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("extender")

DEFAULT_PROMPT = (
    "seamless continuation of the trading card illustration beyond its edges, same art style, "
    "same colours and lighting, detailed background scenery, no text, no letters, no border, "
    "no frame, no card, no logo"
)
NEGATIVE_PROMPT = "text, letters, watermark, logo, frame, border, card, blurry, low quality"


class Backend:
    name = "base"
    multiple = 8          # width/height must be a multiple of this
    megapixels = 1.0      # working resolution the model is happiest at

    def generate(self, image: Image.Image, mask: Image.Image, prompt: str, seed: int, steps: int) -> Image.Image:
        raise NotImplementedError


class PreviewBackend(Backend):
    """CPU only, no model: OpenCV inpainting. For checking layouts and masks, not for printing."""
    name = "preview"
    megapixels = 1.5

    def generate(self, image, mask, prompt, seed, steps):
        small = 4
        rgb = np.asarray(image.reduce(small))
        m = np.asarray(mask.convert("L").reduce(small))
        filled = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (m > 127).astype(np.uint8), 15, cv2.INPAINT_TELEA)
        filled = cv2.GaussianBlur(filled, (0, 0), 6)
        up = cv2.resize(filled, image.size, interpolation=cv2.INTER_CUBIC)
        out = Image.fromarray(cv2.cvtColor(up, cv2.COLOR_BGR2RGB))
        return Image.composite(out, image, mask.convert("L"))


def _torch_dtype():
    import torch
    want = os.environ.get("TORCH_DTYPE", "auto")
    if want != "auto":
        return getattr(torch, want)
    # Turing (Quadro RTX 8000, sm_75) has no native bf16; Ampere and newer do.
    return torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16


def _place(pipe, vram_needed_gb: float):
    import torch
    offload = os.environ.get("CPU_OFFLOAD", "auto")
    free_gb = torch.cuda.mem_get_info()[0] / 1024**3
    if offload == "1" or (offload == "auto" and free_gb < vram_needed_gb):
        log.info("CPU-Offload un (%.1f GB fräi, %.0f GB gebraucht)", free_gb, vram_needed_gb)
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.vae.enable_tiling()
    return pipe


class FluxFillBackend(Backend):
    """FLUX.1 Fill [dev], quantised so it fits 12 GB VRAM and ~15 GB of downloads.

    Transformer: GGUF (Q5_K_S ≈ 8.3 GB). T5: nf4 (≈ 6.3 GB), loaded only while a new prompt
    is encoded and then dropped, so it never sits on the GPU next to the transformer.
    The original repo is gated: HF_TOKEN must belong to an account that accepted the licence.
    """
    name = "flux"
    multiple = 16
    megapixels = 1.6

    def __init__(self):
        import torch
        from diffusers import FluxFillPipeline, FluxTransformer2DModel, GGUFQuantizationConfig
        from huggingface_hub import hf_hub_download, snapshot_download

        model = os.environ.get("FLUX_MODEL", "black-forest-labs/FLUX.1-Fill-dev")
        gguf_repo = os.environ.get("FLUX_GGUF_REPO", "YarvixPA/FLUX.1-Fill-dev-GGUF")
        gguf_file = os.environ.get("FLUX_GGUF_FILE", "flux1-fill-dev-Q5_K_S.gguf")
        self.t5_repo = os.environ.get("FLUX_T5_REPO", "diffusers/FLUX.1-dev-bnb-4bit")
        self.dtype = _torch_dtype()
        self.torch = torch
        self._embeds: dict[str, tuple] = {}

        # Only the small parts of the original repo; it also holds 24 GB transformer + 9.5 GB T5.
        base = snapshot_download(model, allow_patterns=[
            "model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "tokenizer_2/*",
            "vae/*", "transformer/config.json"])
        log.info("Lueden %s/%s (%s)", gguf_repo, gguf_file, self.dtype)
        transformer = FluxTransformer2DModel.from_single_file(
            hf_hub_download(gguf_repo, gguf_file),
            quantization_config=GGUFQuantizationConfig(compute_dtype=self.dtype),
            config=base, subfolder="transformer", torch_dtype=self.dtype)
        pipe = FluxFillPipeline.from_pretrained(base, transformer=transformer, text_encoder_2=None,
                                                torch_dtype=self.dtype)
        self.pipe = _place(pipe, 12)
        self._encode(DEFAULT_PROMPT)

    def _encode(self, prompt: str) -> tuple:
        if prompt in self._embeds:
            return self._embeds[prompt]
        from transformers import T5EncoderModel
        torch = self.torch
        t5 = T5EncoderModel.from_pretrained(self.t5_repo, subfolder="text_encoder_2", torch_dtype=self.dtype)
        for m in t5.modules():  # repo is saved with bf16 compute, which Turing cannot do
            if hasattr(m, "compute_dtype"):
                m.compute_dtype = self.dtype
        self.pipe.text_encoder_2 = t5
        try:
            with torch.no_grad():
                prompt_embeds, pooled, _ = self.pipe.encode_prompt(
                    prompt=prompt, prompt_2=None, device=torch.device("cuda"), max_sequence_length=512)
        finally:
            self.pipe.text_encoder_2 = None
            del t5
            _free_cuda()
        if len(self._embeds) > 32:
            self._embeds.pop(next(iter(self._embeds)))
        self._embeds[prompt] = (prompt_embeds, pooled)
        return self._embeds[prompt]

    def generate(self, image, mask, prompt, seed, steps):
        prompt_embeds, pooled = self._encode(prompt)
        return self.pipe(
            prompt_embeds=prompt_embeds, pooled_prompt_embeds=pooled, image=image, mask_image=mask,
            width=image.width, height=image.height,
            guidance_scale=30.0, num_inference_steps=steps,
            generator=self.torch.Generator("cpu").manual_seed(seed),
        ).images[0]


class SdxlInpaintBackend(Backend):
    """SDXL inpainting — lighter (~10 GB), weaker at large outpaints. Fallback when FLUX does not fit."""
    name = "sdxl"
    megapixels = 1.0

    def __init__(self):
        import torch
        from diffusers import AutoPipelineForInpainting
        model = os.environ.get("SDXL_MODEL", "diffusers/stable-diffusion-xl-1.0-inpainting-0.1")
        log.info("Lueden %s", model)
        self.pipe = _place(AutoPipelineForInpainting.from_pretrained(
            model, torch_dtype=torch.float16, variant="fp16"), 12)
        self.torch = torch

    def generate(self, image, mask, prompt, seed, steps):
        return self.pipe(
            prompt=prompt, negative_prompt=NEGATIVE_PROMPT, image=image, mask_image=mask,
            width=image.width, height=image.height, strength=0.99, guidance_scale=7.0,
            num_inference_steps=steps, generator=self.torch.Generator("cpu").manual_seed(seed),
        ).images[0]


_REGISTRY = {"flux": FluxFillBackend, "sdxl": SdxlInpaintBackend, "preview": PreviewBackend}
_loaded: dict[str, Backend] = {}
_load_lock = threading.Lock()


def available() -> list[str]:
    return list(_REGISTRY)


def get_backend(name: str) -> Backend:
    if name not in _REGISTRY:
        raise ValueError(f"Onbekannte Backend '{name}' ({', '.join(_REGISTRY)})")
    with _load_lock:
        if name not in _loaded:
            # One GPU model at a time: drop the other one before loading.
            for other in [k for k in _loaded if k != "preview" and name != "preview"]:
                del _loaded[other]
                _free_cuda()
            _loaded[name] = _REGISTRY[name]()
        return _loaded[name]


def _free_cuda():
    import gc
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass
