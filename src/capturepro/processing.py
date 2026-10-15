"""Processamento de imagem: ajustes, recorte e redimensionamento (OpenCV).

Princípio: fidelidade. Com todos os ajustes em zero a imagem passa
intacta (bit a bit). Os ajustes são lineares e moderados.
"""
from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

ADJ_RANGES = {
    "brightness": (-100, 100),
    "contrast": (-100, 100),
    "saturation": (-100, 100),
    "sharpness": (0, 100),
}


def is_neutral(adj: dict | None) -> bool:
    if not adj:
        return True
    return all(int(adj.get(k, 0)) == 0 for k in ADJ_RANGES)


@lru_cache(maxsize=64)
def _bc_lut(brightness: int, contrast: int) -> np.ndarray:
    x = np.arange(256, dtype=np.float32)
    factor = 1.0 + contrast / 100.0          # 0.0 .. 2.0
    offset = brightness * 1.28               # -128 .. +128
    y = (x - 127.5) * factor + 127.5 + offset
    return np.clip(np.rint(y), 0, 255).astype(np.uint8)


def apply_adjustments(img: np.ndarray, adj: dict | None) -> np.ndarray:
    """Aplica brilho, contraste, saturação e nitidez. Não altera a entrada."""
    if img is None or is_neutral(adj):
        return img
    b = int(adj.get("brightness", 0))
    c = int(adj.get("contrast", 0))
    s = int(adj.get("saturation", 0))
    sh = int(adj.get("sharpness", 0))
    out = img
    if b or c:
        out = cv2.LUT(out, _bc_lut(b, c))
    if s and out.ndim == 3 and out.shape[2] == 3:
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        f = 1.0 + s / 100.0                  # 0 (cinza) .. 2
        out = cv2.addWeighted(out, f, gray3, 1.0 - f, 0)
    if sh > 0:
        amount = sh / 50.0                   # 0 .. 2 (unsharp mask)
        blur = cv2.GaussianBlur(out, (0, 0), 1.0)
        out = cv2.addWeighted(out, 1.0 + amount, blur, -amount, 0)
    if out is img:
        out = img.copy()
    return out


def crop_to_pixels(width: int, height: int, crop) -> tuple[int, int, int, int]:
    """Converte recorte normalizado (x,y,w,h em 0..1) em pixels (x0,y0,x1,y1)."""
    if not crop:
        return 0, 0, width, height
    x, y, w, h = crop
    x0 = int(round(x * width))
    y0 = int(round(y * height))
    x1 = int(round((x + w) * width))
    y1 = int(round((y + h) * height))
    x0 = min(max(x0, 0), width - 1)
    y0 = min(max(y0, 0), height - 1)
    x1 = min(max(x1, x0 + 1), width)
    y1 = min(max(y1, y0 + 1), height)
    return x0, y0, x1, y1


def apply_crop(img: np.ndarray, crop) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = crop_to_pixels(w, h, crop)
    return img[y0:y1, x0:x1]


def parse_resolution(key: str, custom_w: int = 0, custom_h: int = 0) -> tuple[int, int] | None:
    if not key or key == "original":
        return None
    if key == "custom":
        if custom_w > 0 and custom_h > 0:
            return int(custom_w), int(custom_h)
        return None
    try:
        a, b = key.lower().split("x")
        return int(a), int(b)
    except ValueError:
        return None


def output_size(src_w: int, src_h: int, target: tuple[int, int] | None) -> tuple[int, int, bool]:
    """Tamanho final preservando a proporção dentro da caixa alvo.

    Retorna (largura, altura, exige_interpolacao_para_ampliar).
    """
    if not target:
        return src_w, src_h, False
    tw, th = target
    scale = min(tw / src_w, th / src_h)
    w = max(1, int(round(src_w * scale)))
    h = max(1, int(round(src_h * scale)))
    return w, h, scale > 1.0 + 1e-9


def resize_keep_aspect(img: np.ndarray, target: tuple[int, int] | None) -> np.ndarray:
    h, w = img.shape[:2]
    nw, nh, up = output_size(w, h, target)
    if (nw, nh) == (w, h):
        return img
    interp = cv2.INTER_CUBIC if up else cv2.INTER_AREA
    return cv2.resize(img, (nw, nh), interpolation=interp)


def process_for_save(frame: np.ndarray, crop, adj: dict | None, target: tuple[int, int] | None) -> np.ndarray:
    """Pipeline da foto: recorte (coordenadas reais) → ajustes → redimensionamento."""
    img = apply_crop(frame, crop)
    img = apply_adjustments(np.ascontiguousarray(img), adj)
    img = resize_keep_aspect(img, target)
    return np.ascontiguousarray(img)


def fit_rect(src_w: int, src_h: int, box_w: int, box_h: int) -> tuple[int, int, int, int]:
    """Retângulo (x, y, w, h) onde a imagem cabe na caixa sem deformar."""
    if src_w <= 0 or src_h <= 0 or box_w <= 0 or box_h <= 0:
        return 0, 0, 0, 0
    scale = min(box_w / src_w, box_h / src_h)
    w = max(1, int(src_w * scale))
    h = max(1, int(src_h * scale))
    return (box_w - w) // 2, (box_h - h) // 2, w, h


def make_preview(frame: np.ndarray, box_w: int, box_h: int, adj: dict | None) -> np.ndarray:
    """Reduz o quadro para o tamanho da prévia e aplica os ajustes (RGB)."""
    h, w = frame.shape[:2]
    _, _, pw, ph = fit_rect(w, h, max(box_w, 1), max(box_h, 1))
    if pw <= 0 or ph <= 0:
        pw, ph = w, h
    if pw < w or ph < h:
        small = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)
    else:
        small = frame  # nunca amplia aqui; o pintor escala na tela
    small = apply_adjustments(small, adj)
    if small.ndim == 2:
        return cv2.cvtColor(small, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)


def is_black_frame(frame: np.ndarray, threshold: int = 18) -> bool:
    """Heurística de 'sem sinal': quadro inteiramente preto/escuro."""
    small = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
    return int(small.max()) < threshold


def ensure_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 4:
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    if frame.dtype != np.uint8:
        return cv2.convertScaleAbs(frame, alpha=255.0 / max(1, int(frame.max())))
    return frame
