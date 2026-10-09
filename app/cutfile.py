"""The cut line for print-then-cut (Bambu Suite and other cutters), in millimetres: one closed path,
the slab outline. Nothing else is cut.

Every file uses the full sheet (bleed included) as its coordinate system with the origin in the
top-left corner of print.png, so the cut line lands on the printed image without manual alignment.
"""
from __future__ import annotations

import base64
import math
from pathlib import Path

from .layout import Layout, Rect

STROKE = "#ff0000"  # what most cutter software reads as "cut"


def _f(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _svg_path(r: Rect) -> str:
    x0, y0, x1, y1 = r.x, r.y, r.x + r.w, r.y + r.h
    k = min(r.radius, r.w / 2, r.h / 2)
    if k <= 0:
        return f"M{_f(x0)},{_f(y0)} H{_f(x1)} V{_f(y1)} H{_f(x0)} Z"
    a = f"A{_f(k)},{_f(k)} 0 0 1"
    return (f"M{_f(x0 + k)},{_f(y0)} H{_f(x1 - k)} {a} {_f(x1)},{_f(y0 + k)} "
            f"V{_f(y1 - k)} {a} {_f(x1 - k)},{_f(y1)} H{_f(x0 + k)} {a} {_f(x0)},{_f(y1 - k)} "
            f"V{_f(y0 + k)} {a} {_f(x0 + k)},{_f(y0)} Z")


def _svg(layout: Layout, body: str) -> str:
    w, h = layout.total_w_mm, layout.total_h_mm
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{_f(w)}mm" height="{_f(h)}mm" viewBox="0 0 {_f(w)} {_f(h)}">\n{body}</svg>\n')


def _cut_element(layout: Layout) -> str:
    return f'  <path id="cut" d="{_svg_path(layout.trim)}" fill="none" stroke="{STROKE}" stroke-width="0.1"/>\n'


def write_print_svg(layout: Layout, png: Path, path: Path) -> None:
    """Printed image and cut line in one file, already aligned."""
    data = base64.b64encode(png.read_bytes()).decode()
    image = (f'  <image id="print" x="0" y="0" width="{_f(layout.total_w_mm)}" height="{_f(layout.total_h_mm)}" '
             f'preserveAspectRatio="none" xlink:href="data:image/png;base64,{data}"/>\n')
    path.write_text(_svg(layout, image + _cut_element(layout)))


def _dxf_polyline(r: Rect, sheet_h: float) -> list[str]:
    """One closed polyline with arc bulges. DXF's y axis points up."""
    x0, x1 = r.x, r.x + r.w
    y0, y1 = sheet_h - (r.y + r.h), sheet_h - r.y
    k = min(r.radius, r.w / 2, r.h / 2)
    bulge = math.tan(math.radians(90) / 4)  # quarter circle, counter-clockwise
    if k > 0:
        pts = [(x0 + k, y0, 0), (x1 - k, y0, bulge), (x1, y0 + k, 0), (x1, y1 - k, bulge),
               (x1 - k, y1, 0), (x0 + k, y1, bulge), (x0, y1 - k, 0), (x0, y0 + k, bulge)]
    else:
        pts = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
    out = ["0", "POLYLINE", "8", "CUT", "62", "1", "66", "1", "70", "1", "10", "0", "20", "0", "30", "0"]
    for x, y, b in pts:
        out += ["0", "VERTEX", "8", "CUT", "10", _f(x), "20", _f(y), "30", "0"]
        if b:
            out += ["42", f"{b:.8f}"]
    return out + ["0", "SEQEND", "8", "CUT"]


def write_dxf(layout: Layout, path: Path) -> None:
    """DXF R12, units mm, one closed polyline."""
    h = layout.total_h_mm
    out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009", "9", "$INSUNITS", "70", "4",
           "9", "$EXTMIN", "10", "0", "20", "0", "9", "$EXTMAX", "10", _f(layout.total_w_mm), "20", _f(h),
           "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    out += _dxf_polyline(layout.trim, h)
    out += ["0", "ENDSEC", "0", "EOF"]
    path.write_text("\n".join(out) + "\n")


def write_all(layout: Layout, out_dir: Path) -> None:
    write_dxf(layout, out_dir / "cut.dxf")
    write_print_svg(layout, out_dir / "print.png", out_dir / "print-cut.svg")
