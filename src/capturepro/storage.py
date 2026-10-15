"""Salvamento de imagens com nomes sequenciais e sem sobrescrever arquivos."""
from __future__ import annotations

import datetime as _dt
import os
import re

import cv2
import numpy as np

EXTENSIONS = {"png": ".png", "jpeg": ".jpg", "bmp": ".bmp"}
_KNOWN_EXT = ("png", "jpg", "jpeg", "bmp")
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_prefix(prefix: str) -> str:
    p = _INVALID.sub("", prefix or "").strip().strip(".")
    return p[:60] or "CAPTURA"


def date_string(now: _dt.datetime | None = None) -> str:
    return (now or _dt.datetime.now()).strftime("%Y-%m-%d")


def build_name(prefix: str, date: str, number: int, fmt: str) -> str:
    return f"{sanitize_prefix(prefix)}_{date}_{number:03d}{EXTENSIONS[fmt]}"


def _pattern(prefix: str, date: str) -> re.Pattern:
    return re.compile(
        rf"^{re.escape(sanitize_prefix(prefix))}_{re.escape(date)}_(\d{{3,}})\.({'|'.join(_KNOWN_EXT)})$",
        re.IGNORECASE,
    )


def next_number(folder: str, prefix: str, date: str) -> int:
    """Próximo número livre (maior existente + 1), considerando todas as extensões."""
    pat = _pattern(prefix, date)
    highest = 0
    try:
        for name in os.listdir(folder):
            m = pat.match(name)
            if m:
                highest = max(highest, int(m.group(1)))
    except FileNotFoundError:
        pass
    return highest + 1


def count_today(folder: str, prefix: str, now: _dt.datetime | None = None) -> int:
    pat = _pattern(prefix, date_string(now))
    try:
        return sum(1 for n in os.listdir(folder) if pat.match(n))
    except OSError:
        return 0


def encode_image(img: np.ndarray, fmt: str, jpeg_quality: int = 95) -> bytes:
    ext = EXTENSIONS[fmt]
    params: list[int] = []
    if fmt == "png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    elif fmt == "jpeg":
        q = int(min(max(jpeg_quality, 1), 100))
        params = [cv2.IMWRITE_JPEG_QUALITY, q]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise RuntimeError(f"Falha ao codificar imagem em {fmt.upper()}")
    return buf.tobytes()


def save_image(img: np.ndarray, folder: str, prefix: str, fmt: str = "png",
               jpeg_quality: int = 95, now: _dt.datetime | None = None) -> str:
    """Codifica e grava a imagem. Nunca sobrescreve: usa criação exclusiva ('xb').

    Retorna o caminho completo do arquivo salvo.
    """
    if fmt not in EXTENSIONS:
        raise ValueError(f"Formato desconhecido: {fmt}")
    os.makedirs(folder, exist_ok=True)
    data = encode_image(img, fmt, jpeg_quality)
    date = date_string(now)
    number = next_number(folder, prefix, date)
    for _ in range(100000):
        path = os.path.join(folder, build_name(prefix, date, number, fmt))
        # nome também não pode existir com outra extensão (sequência única)
        stem = os.path.splitext(path)[0]
        if any(os.path.exists(stem + e) for e in (".png", ".jpg", ".jpeg", ".bmp")):
            number += 1
            continue
        try:
            f = open(path, "xb")
        except FileExistsError:
            number += 1
            continue
        try:
            with f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            try:
                os.remove(path)  # nunca deixar arquivo parcial/corrompido
            except OSError:
                pass
            raise
        return path
    raise RuntimeError("Não foi possível encontrar um nome de arquivo livre")
