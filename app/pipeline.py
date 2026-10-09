"""Finished picture in -> slab-sized print sheet plus one cut line out.

The picture is already extended (the card sits somewhere inside it). The card is found, its size
gives the scale (the card is 63 x 88 mm), and the slab outline is placed around it: the card ends
up exactly where the real card lies in the slab.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from . import cutfile
from .card import find_card
from .layout import Layout, Rect, load_layout

MM_PER_INCH = 25.4


@dataclass
class Options:
    template: str = "psa"
    placement: str = "center"     # "center": card centred in the outline; "template": card where the slab holds it
    bleed_mm: float = 2.0
    dpi: int = 260


class CardNotFound(Exception):
    pass


def _place(layout: Layout, placement: str) -> Layout:
    """Move the card inside the outline when it is to be centred. The label keeps its place unless
    it would then reach into the card; then it goes in the middle of the room above the card."""
    if placement != "center":
        return layout
    card, label = layout.card, layout.label
    x = layout.bleed_mm + (layout.width_mm - card.w) / 2
    y = layout.bleed_mm + (layout.height_mm - card.h) / 2
    if label.y + label.h > y:
        label = Rect(label.x, layout.bleed_mm + (y - layout.bleed_mm - label.h) / 2, label.w, label.h, label.radius)
    return Layout(layout.name, layout.width_mm, layout.height_mm, layout.corner_radius_mm,
                  Rect(x, y, card.w, card.h, card.radius), label, layout.white_margin_mm, layout.bleed_mm)


def _sheet_to_source(layout: Layout, box, px_per_mm: float) -> np.ndarray:
    """Affine map from sheet pixels to picture pixels (2x3)."""
    a = np.radians(box.angle)
    rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    src_per_mm = np.array([box.w / layout.card.w, box.h / layout.card.h])
    tl = box.corners()[0]
    lin = rot @ np.diag(src_per_mm / px_per_mm)
    off = tl - rot @ (src_per_mm * np.array([layout.card.x, layout.card.y]))
    return np.hstack([lin, off[:, None]])


def _leading(a: np.ndarray) -> int:
    """Number of True values at the start."""
    return a.size if a.all() else int(np.argmin(a))


def _rounded(draw: ImageDraw.ImageDraw, r: Rect, s: float, **kw):
    x0, y0, x1, y1, rad = r.to_px(s, s)
    draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=rad, **kw)


def _cutout(sheet: Image.Image, layout: Layout, px_per_mm: float) -> Image.Image:
    """Only the slab, transparent outside its outline and inside the label window: Bambu Suite's
    Print Then Cut traces the edges of the picture, so this alone gives the cuts. No bleed."""
    x0, y0, x1, y1, _ = layout.trim.to_px(px_per_mm, px_per_mm)
    out = sheet.crop((x0, y0, x1, y1)).convert("RGBA")
    k = 4  # supersampled mask for a smooth rounded edge
    mask = Image.new("L", (out.width * k, out.height * k), 0)
    r = round(layout.corner_radius_mm * px_per_mm * k)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=r, fill=255)
    _rounded(draw, layout.label.shift(-layout.trim.x, -layout.trim.y), px_per_mm * k, fill=0)
    out.putalpha(mask.resize(out.size, Image.LANCZOS))
    return out


def run(img: Image.Image, opts: Options, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    img = ImageOps.exif_transpose(img).convert("RGB")
    box = find_card(img)
    if box is None:
        raise CardNotFound
    layout = _place(load_layout(opts.template).with_bleed(opts.bleed_mm), opts.placement)

    px_per_mm = opts.dpi / MM_PER_INCH
    pw, ph = round(layout.total_w_mm * px_per_mm), round(layout.total_h_mm * px_per_mm)
    m = _sheet_to_source(layout, box, px_per_mm)
    src = np.asarray(img)
    flags = cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP
    sheet = cv2.warpAffine(src, m, (pw, ph), flags=flags, borderMode=cv2.BORDER_REFLECT_101)

    # Where the picture does not reach the sheet, the mirrored edge is blurred so it reads as background.
    inside = cv2.warpAffine(np.full(src.shape[:2], 255, np.uint8), m, (pw, ph), flags=flags,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    missing = inside < 128
    x0, y0, x1, y1, _ = layout.trim.to_px(px_per_mm, px_per_mm)
    col, row = missing[y0:y1, (x0 + x1) // 2], missing[(y0 + y1) // 2, x0:x1]
    short_mm = {side: round(_leading(a) / px_per_mm, 1) for side, a in
                (("top", col), ("bottom", col[::-1]), ("left", row), ("right", row[::-1]))}
    if missing.any():
        blurred = cv2.GaussianBlur(sheet, (0, 0), 3 * px_per_mm)
        soft = cv2.GaussianBlur((~missing).astype(np.float32), (0, 0), 0.5 * px_per_mm)[..., None]
        sheet = (sheet * soft + blurred * (1 - soft)).astype(np.uint8)

    out = Image.fromarray(sheet)
    out.save(out_dir / "print.png", dpi=(opts.dpi, opts.dpi))
    out.save(out_dir / "print.pdf", resolution=opts.dpi)
    cutfile.write_all(layout, out_dir)
    cut_png = _cutout(out, layout, px_per_mm)
    # dpi from the rounded pixel size, so the Suite imports it at exactly the slab size
    cut_png.save(out_dir / "cutout.png", dpi=(cut_png.width / layout.width_mm * MM_PER_INCH,
                                              cut_png.height / layout.height_mm * MM_PER_INCH))

    # Preview: the picture with the cut line on top and everything outside it dimmed.
    preview = out.copy()
    shade = Image.new("L", out.size, 150)
    _rounded(ImageDraw.Draw(shade), layout.trim, px_per_mm, fill=0)
    _rounded(ImageDraw.Draw(shade), layout.label, px_per_mm, fill=150)
    preview.paste(Image.new("RGB", out.size, (255, 255, 255)), (0, 0), shade)
    pd = ImageDraw.Draw(preview)
    for r in cutfile.cut_rects(layout):
        _rounded(pd, r, px_per_mm, outline=(230, 0, 0), width=max(2, round(0.3 * px_per_mm)))
    preview.save(out_dir / "preview.jpg", quality=92)

    meta = {
        "template": layout.name, "size_mm": [layout.width_mm, layout.height_mm],
        "sheet_mm": [layout.total_w_mm, layout.total_h_mm], "print_px": [pw, ph], "dpi": opts.dpi,
        "card_px": {"cx": round(box.cx, 1), "cy": round(box.cy, 1), "w": round(box.w, 1), "h": round(box.h, 1),
                    "angle": round(box.angle, 2)},
        "source_dpi": round(box.w / layout.card.w * MM_PER_INCH),
        "missing_mm": short_mm,
        "label_edge_mm": round(layout.label.y - layout.trim.y, 1),  # strip left between label window and top edge
        "options": asdict(opts), "created": int(time.time()),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta
