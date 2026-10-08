"""Card in -> slab-sized print sheet out, with the card and label areas left white."""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .backends import DEFAULT_PROMPT, get_backend
from .card import prepare_card
from .layout import Layout, Rect, load_layout

log = logging.getLogger("extender")
MM_PER_INCH = 25.4


@dataclass
class Options:
    template: str = "psa"
    backend: str = "flux"
    prompt: str = ""
    seed: int = -1
    steps: int = 40
    inset_mm: float = 2.5    # the card's own frame gets repainted so the art, not the border, continues
    bleed_mm: float = 0.0
    dpi: int = 300
    guides: bool = False
    detect_card: bool = True


def _round_to(v: float, m: int) -> int:
    return max(m, int(round(v / m)) * m)


def _rounded(draw: ImageDraw.ImageDraw, r: Rect, sx: float, sy: float, fill, outline=None, width=1):
    x0, y0, x1, y1, rad = r.to_px(sx, sy)
    draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=rad, fill=fill, outline=outline, width=width)


def _gen_canvas(layout: Layout, card: Image.Image, opts: Options, multiple: int, megapixels: float):
    scale = math.sqrt(megapixels * 1e6 / (layout.total_w_mm * layout.total_h_mm))
    gw = _round_to(layout.total_w_mm * scale, multiple)
    gh = _round_to(layout.total_h_mm * scale, multiple)
    sx, sy = gw / layout.total_w_mm, gh / layout.total_h_mm

    x0, y0, x1, y1, _ = layout.card.to_px(sx, sy)
    card_px = card.resize((x1 - x0, y1 - y0), Image.LANCZOS)

    # Unknown area starts as the card's average colour, a calm prior for the model.
    avg = card_px.resize((1, 1), Image.BOX).getpixel((0, 0))
    init = Image.new("RGB", (gw, gh), avg)
    init.paste(card_px, (x0, y0))

    mask = Image.new("L", (gw, gh), 255)
    keep = Rect(layout.card.x, layout.card.y, layout.card.w, layout.card.h).grow(-opts.inset_mm)
    _rounded(ImageDraw.Draw(mask), keep, sx, sy, fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    return init, mask, (sx, sy)


def _font(size: int):
    for name in ("DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def run(card_img: Image.Image, opts: Options, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    layout = load_layout(opts.template).with_bleed(opts.bleed_mm)
    seed = opts.seed if opts.seed >= 0 else int(time.time() * 1000) % 2**31
    prompt = opts.prompt.strip() or DEFAULT_PROMPT

    card = prepare_card(card_img, opts.detect_card)
    card.save(out_dir / "card.png")

    backend = get_backend(opts.backend)
    init, mask, _ = _gen_canvas(layout, card, opts, backend.multiple, backend.megapixels)
    mask.save(out_dir / "mask.png")
    t0 = time.time()
    log.info("%s: %dx%d, seed %d, %d steps", backend.name, *init.size, seed, opts.steps)
    raw = backend.generate(init, mask, prompt, seed, opts.steps)
    gen_seconds = round(time.time() - t0, 1)
    raw.save(out_dir / "raw.png")

    # Print resolution
    px_per_mm = opts.dpi / MM_PER_INCH
    pw, ph = round(layout.total_w_mm * px_per_mm), round(layout.total_h_mm * px_per_mm)
    art = raw.resize((pw, ph), Image.LANCZOS)

    sheet = art.copy()
    d = ImageDraw.Draw(sheet)
    margin = layout.white_margin_mm
    _rounded(d, layout.card.grow(margin), px_per_mm, px_per_mm, fill="white")
    _rounded(d, layout.label.grow(margin), px_per_mm, px_per_mm, fill="white")
    if opts.guides:
        _rounded(d, layout.trim, px_per_mm, px_per_mm, fill=None, outline=(160, 160, 160),
                 width=max(1, round(0.1 * px_per_mm)))
    sheet.save(out_dir / "print.png", dpi=(opts.dpi, opts.dpi))
    sheet.save(out_dir / "print.pdf", resolution=opts.dpi)

    # Preview: how it looks in the case with the card and a label in place.
    preview = art.copy()
    x0, y0, x1, y1, rad = layout.card.to_px(px_per_mm, px_per_mm)
    card_mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), radius=rad, fill=255)
    preview.paste(card.resize(card_mask.size, Image.LANCZOS), (x0, y0), card_mask)
    pd = ImageDraw.Draw(preview)
    lx0, ly0, lx1, ly1, lrad = layout.label.to_px(px_per_mm, px_per_mm)
    pd.rounded_rectangle((lx0, ly0, lx1, ly1), radius=lrad, fill="white",
                         outline=(200, 30, 40), width=max(2, round(0.8 * px_per_mm)))
    pd.text(((lx0 + lx1) // 2, (ly0 + ly1) // 2), "LABEL", fill=(120, 120, 120),
            font=_font(round(4 * px_per_mm)), anchor="mm")
    preview.save(out_dir / "preview.jpg", quality=92)

    meta = {
        "template": layout.name, "size_mm": [layout.total_w_mm, layout.total_h_mm],
        "print_px": [pw, ph], "dpi": opts.dpi, "seed": seed, "prompt": prompt,
        "gen_px": list(init.size), "gen_seconds": gen_seconds, "options": asdict(opts),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta
