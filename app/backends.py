"""Outpainting engines. Each takes an init image + mask (white = paint) and returns an image of the same size."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

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


def _offload_blocks(pipe) -> None:
    """For small cards: the transformer's 57 blocks stay in RAM and each one visits the GPU only
    for its own forward pass; everything else stays on the GPU. accelerate's sequential offload
    moves single weights and breaks GGUF-quantised layers, whole blocks keep them intact."""
    import torch
    gpu, cpu = torch.device("cuda"), torch.device("cpu")

    def to_gpu(module, args):
        module.to(gpu)

    def to_cpu(module, args, output):
        module.to(cpu)

    transformer = pipe.transformer
    for name, child in transformer.named_children():
        if name in ("transformer_blocks", "single_transformer_blocks"):
            for block in child:
                block.to(cpu)
                block.register_forward_pre_hook(to_gpu)
                block.register_forward_hook(to_cpu)
        else:
            child.to(gpu)
    for name in ("vae", "text_encoder"):
        getattr(pipe, name).to(gpu)


def _place(pipe, vram_needed_gb: float):
    """All on the GPU when it fits; else whole models move in and out (model offload). Cards under
    11 GB (from 6 GB) move the transformer block by block: ~3.3 GB peak."""
    import torch
    from . import models
    offload = os.environ.get("CPU_OFFLOAD", "auto")
    total_gb = models.gpu_total_gb()
    free_gb = min(torch.cuda.mem_get_info()[0] / 1024**3, total_gb)
    if offload == "sequential" or (offload == "auto" and total_gb < 11):
        log.info("Block-wise CPU offload (%.1f GB VRAM)", total_gb)
        _offload_blocks(pipe)
    elif offload == "1" or (offload == "auto" and free_gb < vram_needed_gb):
        log.info("CPU offload on (%.1f GB free, %.1f GB needed)", free_gb, vram_needed_gb)
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    pipe.vae.enable_tiling()
    return pipe


class FluxFillBackend(Backend):
    """FLUX.1 Fill [dev], quantised to fit cards from 6 GB VRAM (model files: app/models.py).

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

        vram = models.gpu_total_gb()
        limit = float(os.environ.get("VRAM_LIMIT_GB", "0") or 0)
        if limit > 0:
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            torch.cuda.set_per_process_memory_fraction(min(1.0, limit / total))
        # Cards under 11 GB paint at a lower working resolution; the print is scaled up anyway.
        self.megapixels = float(os.environ.get("GEN_MEGAPIXELS", "0") or 0) or (1.6 if vram >= 11 else 1.0)

        base = models.base_dir()
        log.info("Loading %s/%s (%s, %.1f GB VRAM, %.1f MP)",
                 models.GGUF_REPO, models.gguf_file(), self.dtype, vram, self.megapixels)
        gguf = models.gguf_path()
        transformer = FluxTransformer2DModel.from_single_file(
            gguf,
            quantization_config=GGUFQuantizationConfig(compute_dtype=self.dtype),
            config=base, subfolder="transformer", torch_dtype=self.dtype)
        pipe = FluxFillPipeline.from_pretrained(base, transformer=transformer, text_encoder_2=None,
                                                torch_dtype=self.dtype)
        self.pipe = _place(pipe, os.path.getsize(gguf) / 1024**3 + 3.5)
        self._load_shipped_embeds()

    def _load_shipped_embeds(self) -> None:
        """Embeddings of DEFAULT_PROMPT, computed once with T5, so T5 is never needed for it."""
        from safetensors import safe_open
        path = Path(__file__).parent / "assets" / "prompt_embeds.safetensors"
        if not path.is_file():
            return
        with safe_open(str(path), framework="pt") as f:
            if f.metadata().get("prompt") != DEFAULT_PROMPT:
                log.warning("%s belongs to another prompt, ignoring it", path.name)
                return
            self._embeds[DEFAULT_PROMPT] = tuple(
                f.get_tensor(k).to("cuda", self.dtype) for k in ("prompt_embeds", "pooled_prompt_embeds"))

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


def free_gpu() -> None:
    """After an out-of-memory error: give back what the failed job held."""
    _free_cuda()


def _free_cuda():
    import gc
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass
