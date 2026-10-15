"""Descoberta de dispositivos de captura e dos seus modos de vídeo."""
from __future__ import annotations

import glob
import logging
import os
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
TEST_SOURCE_KEY = "__teste__"
TEST_SOURCE_NAME = "Fonte de teste (vídeo simulado)"

FOURCC_HINTS = {
    "YUY2": "sem compressão", "UYVY": "sem compressão", "NV12": "sem compressão",
    "YV12": "sem compressão", "I420": "sem compressão", "RGB24": "sem compressão",
    "RGB32": "sem compressão", "MJPG": "comprimido", "H264": "comprimido",
}

STANDARD_FPS = [120, 60, 59.94, 50, 30, 29.97, 25, 24, 20, 15, 10, 5]

PROBE_RESOLUTIONS = [
    (640, 480), (720, 480), (720, 576), (800, 600), (1024, 768), (1280, 720),
    (1280, 1024), (1600, 1200), (1920, 1080), (2560, 1440), (3840, 2160),
]


def test_source_enabled() -> bool:
    return os.environ.get("CAPTUREPRO_TEST_SOURCE") == "1"


@dataclass
class DeviceInfo:
    index: int          # índice para o OpenCV (ordem DirectShow / /dev/videoN)
    name: str           # nome amigável
    key: str            # chave estável para memorizar configurações

    @property
    def is_test(self) -> bool:
        return self.key == TEST_SOURCE_KEY


@dataclass
class VideoMode:
    width: int
    height: int
    fourcc: str | None = None
    min_fps: float | None = None
    max_fps: float | None = None
    default_fps: float | None = None

    def label(self) -> str:
        s = f"{self.width} × {self.height}"
        if self.fourcc:
            hint = FOURCC_HINTS.get(self.fourcc)
            s += f"  ·  {self.fourcc}" + (f" ({hint})" if hint else "")
        return s

    def ident(self) -> tuple:
        return (self.width, self.height, self.fourcc)

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height, "fourcc": self.fourcc,
                "min_fps": self.min_fps, "max_fps": self.max_fps, "default_fps": self.default_fps}

    @classmethod
    def from_dict(cls, d: dict) -> "VideoMode":
        return cls(int(d["width"]), int(d["height"]), d.get("fourcc"),
                   d.get("min_fps"), d.get("max_fps"), d.get("default_fps"))

    def fps_options(self) -> list[float]:
        lo, hi = self.min_fps, self.max_fps
        if not hi:
            return []
        lo = lo or hi
        opts = [f for f in STANDARD_FPS if lo - 0.01 <= f <= hi + 0.01]
        top = round(hi, 2)
        if all(abs(top - f) > 0.05 for f in opts):
            opts.insert(0, top)
        return sorted(set(opts), reverse=True)


@dataclass
class DeviceCaps:
    modes: list[VideoMode] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    current_input: int | None = None
    from_driver: bool = False   # True = lista lida do driver (não sondada)


def _dedupe_modes(raw: list[dict]) -> list[VideoMode]:
    best: dict[tuple, VideoMode] = {}
    for d in raw:
        m = VideoMode.from_dict(d)
        k = m.ident()
        if k in best:
            b = best[k]
            b.max_fps = max(filter(None, [b.max_fps, m.max_fps]), default=None)
            b.min_fps = min(filter(None, [b.min_fps, m.min_fps]), default=None)
        else:
            best[k] = m
    order = {"YUY2": 0, "UYVY": 0, "NV12": 1, "RGB24": 1, "RGB32": 1, "I420": 1, "YV12": 1, "MJPG": 2, "H264": 3}
    return sorted(best.values(), key=lambda m: (-(m.width * m.height), order.get(m.fourcc or "", 1), m.fourcc or ""))


def _make_keys(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    keys = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        keys.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return keys


def _probe_opencv_names(max_index: int = 8) -> list[str]:
    """Plano B (DirectShow não consultável): testa índices pelo OpenCV."""
    import cv2
    names = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        ok = cap.isOpened()
        cap.release()
        if not ok:
            break
        names.append(f"Dispositivo de vídeo {i + 1}")
    return names


def list_devices() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []
    if IS_WINDOWS:
        from . import dshow
        names = dshow.list_device_names()
        if names is None:
            names = _probe_opencv_names()
        for i, (n, k) in enumerate(zip(names, _make_keys(names))):
            devices.append(DeviceInfo(i, n, k))
    else:
        for path in sorted(glob.glob("/dev/video*")):
            try:
                idx = int(path.replace("/dev/video", ""))
            except ValueError:
                continue
            name = path
            sysname = f"/sys/class/video4linux/video{idx}/name"
            try:
                with open(sysname, encoding="utf-8") as f:
                    name = f"{f.read().strip()} ({path})"
            except OSError:
                pass
            devices.append(DeviceInfo(idx, name, name))
    if test_source_enabled():
        devices.append(DeviceInfo(-1, TEST_SOURCE_NAME, TEST_SOURCE_KEY))
    return devices


def query_caps(dev: DeviceInfo) -> DeviceCaps:
    if dev.is_test:
        modes = [VideoMode(1920, 1080, "TEST", 5, 30, 30), VideoMode(1280, 720, "TEST", 5, 60, 30),
                 VideoMode(720, 576, "TEST", 5, 25, 25)]
        return DeviceCaps(modes, [{"pin": 0, "out_pin": 0, "type": 6, "label": "Digital serial (SDI/HDMI)"},
                                  {"pin": 1, "out_pin": 0, "type": 2, "label": "Composto (RCA)"}], 0, True)
    if IS_WINDOWS:
        from . import dshow
        modes = _dedupe_modes(dshow.query_modes(dev.index))
        inputs, current = dshow.query_inputs(dev.index)
        return DeviceCaps(modes, inputs, current, bool(modes))
    return DeviceCaps([], [], None, False)


def route_input(dev: DeviceInfo, inp: dict) -> bool:
    if dev.is_test:
        return True
    if IS_WINDOWS:
        from . import dshow
        return dshow.route_input(dev.index, int(inp["out_pin"]), int(inp["pin"]))
    return False


def device_present(key: str) -> DeviceInfo | None:
    """Procura o dispositivo pela chave (o índice pode mudar após reconectar)."""
    for d in list_devices():
        if d.key == key:
            return d
    return None
