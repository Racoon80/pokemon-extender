"""Slab layout: everything is defined in millimetres and converted to pixels late."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
# Own or corrected formats; a file here wins over a built-in one with the same name.
USER_TEMPLATE_DIR = Path(os.environ.get("USER_TEMPLATE_DIR", "/data/templates"))


def _template_path(name: str) -> Path | None:
    for d in (USER_TEMPLATE_DIR, TEMPLATE_DIR):
        if (d / f"{name}.json").is_file():
            return d / f"{name}.json"
    return None


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    radius: float = 0.0

    def grow(self, d: float) -> "Rect":
        return Rect(self.x - d, self.y - d, self.w + 2 * d, self.h + 2 * d, max(0.0, self.radius + d))

    def shift(self, dx: float, dy: float) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h, self.radius)

    def to_px(self, sx: float, sy: float) -> tuple[int, int, int, int, int]:
        x0, y0 = round(self.x * sx), round(self.y * sy)
        x1, y1 = round((self.x + self.w) * sx), round((self.y + self.h) * sy)
        return x0, y0, x1, y1, round(self.radius * (sx + sy) / 2)


@dataclass(frozen=True)
class Layout:
    name: str
    width_mm: float
    height_mm: float
    corner_radius_mm: float
    card: Rect
    label: Rect
    white_margin_mm: float
    bleed_mm: float = 0.0

    @property
    def total_w_mm(self) -> float:
        return self.width_mm + 2 * self.bleed_mm

    @property
    def total_h_mm(self) -> float:
        return self.height_mm + 2 * self.bleed_mm

    def with_bleed(self, bleed_mm: float) -> "Layout":
        """Bleed grows the sheet on every side; card and label move with it."""
        d = bleed_mm - self.bleed_mm
        return Layout(self.name, self.width_mm, self.height_mm, self.corner_radius_mm,
                      self.card.shift(d, d), self.label.shift(d, d), self.white_margin_mm, bleed_mm)

    @property
    def trim(self) -> Rect:
        return Rect(self.bleed_mm, self.bleed_mm, self.width_mm, self.height_mm, self.corner_radius_mm)


def _rect(d: dict) -> Rect:
    return Rect(d["x_mm"], d["y_mm"], d["w_mm"], d["h_mm"], d.get("radius_mm", 0.0))


def load_layout(name: str) -> Layout:
    path = _template_path(name)
    if path is None:
        raise ValueError(f"Template '{name}' does not exist ({', '.join(list_layouts())})")
    d = json.loads(path.read_text())
    layout = Layout(d["name"], d["width_mm"], d["height_mm"], d.get("corner_radius_mm", 0.0),
                    _rect(d["card"]), _rect(d["label"]), d.get("white_margin_mm", 0.0))
    for part in (layout.card, layout.label):
        if part.x < 0 or part.y < 0 or part.x + part.w > layout.width_mm or part.y + part.h > layout.height_mm:
            raise ValueError(f"{path.name}: an area lies outside the sheet")
    return layout


def list_layouts() -> list[str]:
    return sorted({p.stem for d in (TEMPLATE_DIR, USER_TEMPLATE_DIR) if d.is_dir() for p in d.glob("*.json")})
