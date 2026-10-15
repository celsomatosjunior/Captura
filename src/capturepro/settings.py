"""Persistência de configurações (JSON em %APPDATA%\\CapturePro\\config.json).

Configurações globais (pasta, prefixo, formato, última placa...) e
configurações por dispositivo (modo de vídeo, recorte, ajustes, entrada).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import threading
import time

from . import APP_NAME

log = logging.getLogger(__name__)

NEUTRAL_ADJUSTMENTS = {"brightness": 0, "contrast": 0, "saturation": 0, "sharpness": 0}

OUTPUT_RESOLUTIONS = [
    ("original", "Original"),
    ("640x480", "640 × 480"),
    ("800x600", "800 × 600"),
    ("1024x768", "1024 × 768"),
    ("1280x720", "1280 × 720"),
    ("1920x1080", "1920 × 1080"),
    ("custom", "Personalizada"),
]

IMAGE_FORMATS = [("png", "PNG (sem perda)"), ("jpeg", "JPEG"), ("bmp", "BMP")]


def config_dir() -> str:
    override = os.environ.get("CAPTUREPRO_CONFIG_DIR")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def default_output_folder() -> str:
    home = os.path.expanduser("~")
    pictures = os.path.join(home, "Pictures")
    if not os.path.isdir(pictures):
        pictures = home
    return os.path.join(pictures, "Capturas")


def _defaults() -> dict:
    return {
        "version": 1,
        "last_device": None,
        "backend": "dshow" if sys.platform == "win32" else "auto",
        "output_folder": default_output_folder(),
        "prefix": "CAPTURA",
        "format": "png",
        "jpeg_quality": 95,
        "output_resolution": "original",
        "custom_width": 1920,
        "custom_height": 1080,
        "autostart": False,
        "window_geometry": None,
        "window_maximized": False,
        "devices": {},
    }


def _device_defaults() -> dict:
    return {
        "mode": None,          # {"width":..,"height":..,"fps":..,"fourcc":..} ou None = padrão
        "fps": None,           # taxa de quadros escolhida (None = padrão do modo)
        "crop": None,          # [x, y, w, h] normalizado 0..1 ou None = imagem inteira
        "adjustments": dict(NEUTRAL_ADJUSTMENTS),
        "input": None,         # índice do pino de entrada do crossbar (None = padrão do driver)
        "probed_modes": None,  # cache de resoluções detectadas por sondagem
    }


def _merge(defaults: dict, data: dict) -> dict:
    out = copy.deepcopy(defaults)
    if isinstance(data, dict):
        for k, v in data.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict) and k != "devices":
                out[k] = _merge(out[k], v)
            else:
                out[k] = v
    return out


def _valid_crop(c) -> list | None:
    try:
        if c is None:
            return None
        x, y, w, h = (float(v) for v in c)
        if w <= 0 or h <= 0:
            return None
        x = min(max(x, 0.0), 1.0)
        y = min(max(y, 0.0), 1.0)
        w = min(w, 1.0 - x)
        h = min(h, 1.0 - y)
        if w < 0.005 or h < 0.005:
            return None
        return [x, y, w, h]
    except Exception:
        return None


class Settings:
    """Configurações com gravação atômica e tolerância a arquivo corrompido."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(config_dir(), "config.json")
        self._lock = threading.RLock()
        self.data = _defaults()
        self.load()

    # ------------------------------------------------------------------ io
    def load(self) -> None:
        with self._lock:
            if not os.path.exists(self.path):
                self.data = _defaults()
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.data = _merge(_defaults(), raw)
                if not isinstance(self.data.get("devices"), dict):
                    self.data["devices"] = {}
            except Exception as e:  # arquivo corrompido: guarda cópia e recomeça
                log.warning("Configuração inválida (%s); usando padrões", e)
                try:
                    os.replace(self.path, self.path + f".corrompido-{int(time.time())}")
                except OSError:
                    pass
                self.data = _defaults()

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except OSError as e:
                log.error("Falha ao salvar configurações: %s", e)

    # ------------------------------------------------------------- globais
    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key, value) -> None:
        with self._lock:
            self.data[key] = value

    # ------------------------------------------------------- por dispositivo
    def device(self, key: str) -> dict:
        with self._lock:
            raw = self.data["devices"].get(key, {})
            d = _merge(_device_defaults(), raw)
            d["adjustments"] = _merge(NEUTRAL_ADJUSTMENTS, d.get("adjustments") or {})
            d["crop"] = _valid_crop(d.get("crop"))
            return d

    def update_device(self, key: str, **values) -> None:
        if not key:
            return
        with self._lock:
            d = self.device(key)
            for k, v in values.items():
                if k == "crop":
                    v = _valid_crop(v)
                d[k] = copy.deepcopy(v)
            self.data["devices"][key] = d
