"""Outpainting engines. Each takes an init image + mask (white = paint) and returns an image of the same size."""
from __future__ import annotations

import logging
import os
import threading

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("extender")

# FLUX reads negations ("no frame") as requests, and "card" makes it paint cards: describe only what is wanted.
DEFAULT_PROMPT = (
    "A seamless painterly anime landscape illustration that fills the entire image edge to edge. "
    "The scenery continues naturally in every direction with the same art style, colours and lighting. "
    "Highly detailed."
)


def _no_progress(stage: str, step: int = 0, steps: int = 0) -> None:
    pass


class Backend:
    name = "base"
    multiple = 8          # width/height must be a multiple of this
    megapixels = 1.0      # working resolution the model is happiest at

    def generate(self, image: Image.Image, mask: Image.Image, prompt: str, seed: int, steps: int,
                 progress=_no_progress) -> Image.Image:
        """progress(stage, step, steps) with stage "encoding" or "generating"."""
        raise NotImplementedError

    @staticmethod
    def _step_callback(progress, steps):
        def cb(pipe, i, t, kwargs):
            progress("generating", i + 1, steps)
            return kwargs
        return cb


class PreviewBackend(Backend):
    """CPU only, no model: OpenCV inpainting. For checking layouts and masks, not for printing."""
    name = "preview"
    megapixels = 1.5

    def generate(self, image, mask, prompt, seed, steps, progress=_no_progress):
        progress("generating", 0, 1)
        small = 4
        rgb = np.asarray(image.reduce(small))
        m = np.asarray(mask.convert("L").reduce(small))
        filled = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (m > 127).astype(np.uint8), 15, cv2.INPAINT_TELEA)
        filled = cv2.GaussianBlur(filled, (0, 0), 6)
        up = cv2.resize(filled, image.size, interpolation=cv2.INTER_CUBIC)
        out = Image.fromarray(cv2.cvtColor(up, cv2.COLOR_BGR2RGB))
        progress("generating", 1, 1)
        return Image.composite(out, image, mask.convert("L"))


def _torch_dtype():
    import torch
    want = os.environ.get("TORCH_DTYPE", "auto")
    if want != "auto":
        return getattr(torch, want)
    # FLUX overflows to NaN in fp16 (black images). Ampere and newer have native bf16; on older
    # cards (Turing, e.g. Quadro RTX 8000) emulated bf16 is slower than plain fp32.
    return torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float32


def _place(pipe, vram_needed_gb: float):
    import torch
    offload = os.environ.get("CPU_OFFLOAD", "auto")
    free_gb = torch.cuda.mem_get_info()[0] / 1024**3
    if offload == "1" or (offload == "auto" and free_gb < vram_needed_gb):
        log.info("CPU offload on (%.1f GB free, %.0f GB needed)", free_gb, vram_needed_gb)
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.vae.enable_tiling()
    return pipe


class FluxFillBackend(Backend):
    """FLUX.1 Fill [dev], quantised so it fits 12 GB VRAM (model files: app/models.py).

    Transformer: GGUF (Q5_K_S ≈ 8.3 GB). T5: nf4 (≈ 6.3 GB), loaded only while a new prompt
    is encoded and then dropped, so it never sits on the GPU next to the transformer.
    """
    name = "flux"
    multiple = 16
    megapixels = 1.6

    def __init__(self):
        import torch
        from diffusers import FluxFillPipeline, FluxTransformer2DModel, GGUFQuantizationConfig

        from . import models

        self.dtype = _torch_dtype()
        self.torch = torch
        self._embeds: dict[str, tuple] = {}

        base = models.base_dir()
        log.info("Loading %s/%s (%s)", models.GGUF_REPO, models.GGUF_FILE, self.dtype)
        transformer = FluxTransformer2DModel.from_single_file(
            models.gguf_path(),
            quantization_config=GGUFQuantizationConfig(compute_dtype=self.dtype),
            config=base, subfolder="transformer", torch_dtype=self.dtype)
        pipe = FluxFillPipeline.from_pretrained(base, transformer=transformer, text_encoder_2=None,
                                                torch_dtype=self.dtype)
        self.pipe = _place(pipe, 12)
        self._encode(DEFAULT_PROMPT)

    def _encode(self, prompt: str, progress=_no_progress) -> tuple:
        if prompt in self._embeds:
            return self._embeds[prompt]
        progress("encoding")
        from transformers import T5EncoderModel

        from . import models
        torch = self.torch
        t5 = T5EncoderModel.from_pretrained(models.t5_dir(), subfolder="text_encoder_2", torch_dtype=self.dtype)
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

    def generate(self, image, mask, prompt, seed, steps, progress=_no_progress):
        prompt_embeds, pooled = self._encode(prompt, progress)
        progress("generating", 0, steps)
        return self.pipe(
            prompt_embeds=prompt_embeds, pooled_prompt_embeds=pooled, image=image, mask_image=mask,
            width=image.width, height=image.height,
            guidance_scale=30.0, num_inference_steps=steps,
            generator=self.torch.Generator("cpu").manual_seed(seed),
            callback_on_step_end=self._step_callback(progress, steps),
        ).images[0]


_REGISTRY = {"flux": FluxFillBackend, "preview": PreviewBackend}
_loaded: dict[str, Backend] = {}
_load_lock = threading.Lock()


def available() -> list[str]:
    return list(_REGISTRY)


def is_loaded(name: str) -> bool:
    return name in _loaded


def get_backend(name: str) -> Backend:
    if name not in _REGISTRY:
        raise ValueError(f"Unknown backend '{name}' ({', '.join(_REGISTRY)})")
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
