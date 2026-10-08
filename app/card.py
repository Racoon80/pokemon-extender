"""Get a straight, tightly cropped card out of whatever was uploaded."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageOps

CARD_ASPECT = 63 / 88


def _order(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def _find_quad(bgr: np.ndarray) -> np.ndarray | None:
    """Largest card-shaped quadrilateral, or None when the photo has none."""
    h, w = bgr.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < 0.2 * w * h:
            break
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        quad = _order(approx.reshape(4, 2).astype(np.float32))
        qw = np.linalg.norm(quad[1] - quad[0])
        qh = np.linalg.norm(quad[3] - quad[0])
        if qh and abs(min(qw, qh) / max(qw, qh) - CARD_ASPECT) < 0.08:
            return quad
    return None


def prepare_card(img: Image.Image, detect: bool = True) -> Image.Image:
    """Return the card upright in 63:88. An image that already is the card is kept as is."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    if abs(img.width / img.height - CARD_ASPECT) < 0.02 or not detect:
        return img

    quad = _find_quad(cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR))
    if quad is None:
        # No outline found: centre-crop to the card aspect rather than distort it.
        target_w = min(img.width, round(img.height * CARD_ASPECT))
        target_h = min(img.height, round(target_w / CARD_ASPECT))
        left, top = (img.width - target_w) // 2, (img.height - target_h) // 2
        return img.crop((left, top, left + target_w, top + target_h))

    out_h = int(max(np.linalg.norm(quad[3] - quad[0]), np.linalg.norm(quad[2] - quad[1])))
    out_w = round(out_h * CARD_ASPECT)
    if np.linalg.norm(quad[1] - quad[0]) > np.linalg.norm(quad[3] - quad[0]):
        quad = np.roll(quad, -1, axis=0)  # card lies on its side in the photo
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
    warped = cv2.warpPerspective(np.asarray(img), cv2.getPerspectiveTransform(quad, dst), (out_w, out_h),
                                 flags=cv2.INTER_CUBIC)
    return Image.fromarray(warped)
