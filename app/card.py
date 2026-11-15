"""Find the card inside a finished (already extended) picture."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

CARD_ASPECT = 63 / 88


@dataclass(frozen=True)
class CardBox:
    """The card in source pixels: centre, size (upright) and rotation in degrees."""
    cx: float
    cy: float
    w: float
    h: float
    angle: float

    def corners(self) -> np.ndarray:
        """Top-left, top-right, bottom-right, bottom-left."""
        a = np.radians(self.angle)
        ux, uy = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
        c = np.array([self.cx, self.cy])
        hw, hh = ux * self.w / 2, uy * self.h / 2
        return np.array([c - hw - hh, c + hw - hh, c + hw + hh, c - hw + hh])


def _candidates(gray: np.ndarray):
    for lo, hi in ((40, 120), (20, 60), (10, 30)):
        edges = cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        yield from contours


FULL_FRAME_TOLERANCE = 0.04


def find_card(img: Image.Image) -> CardBox | None:
    """Largest card-shaped rectangle that lies inside the picture, or None.

    A picture that is only the card (a scan or a shop photo, edge to edge) has no edge around the
    card to find; if the whole picture has a card's proportions it is taken as the card, and the
    pipeline fills the surroundings with blurred background."""
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    best = None
    for c in _candidates(gray):
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(c)
        area = rw * rh
        if not 0.1 * w * h < area < 0.9 * w * h:
            continue
        if abs(min(rw, rh) / max(rw, rh) - CARD_ASPECT) > 0.03:
            continue
        if cv2.contourArea(cv2.convexHull(c)) < 0.97 * area:  # a rectangle, not a blob
            continue
        if rw > rh:  # minAreaRect may describe the upright card lying on its side
            rw, rh, angle = rh, rw, angle - 90
        angle = (angle + 45) % 90 - 45
        if best is None or area > best.w * best.h:
            best = CardBox(cx, cy, rw, rh, angle)
    if best is None and w < h and abs(w / h - CARD_ASPECT) <= FULL_FRAME_TOLERANCE:
        return CardBox(w / 2, h / 2, w, h, 0.0)
    return best
