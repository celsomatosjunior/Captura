"""Thread de captura: abre o dispositivo, lê quadros reais, gera a prévia,
detecta falta de sinal e reconecta automaticamente.

A interface nunca toca no dispositivo diretamente; tudo passa por aqui.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")  # abre MSMF mais rápido
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from . import devices, processing  # noqa: E402
from .devices import DeviceInfo, VideoMode  # noqa: E402

log = logging.getLogger(__name__)

BACKENDS = {
    "dshow": ("DirectShow (recomendado)", getattr(cv2, "CAP_DSHOW", 700)),
    "msmf": ("Media Foundation", getattr(cv2, "CAP_MSMF", 1400)),
    "auto": ("Automático", cv2.CAP_ANY),
}

# estados para a interface
ST_CONNECTING = "connecting"
ST_LIVE = "live"
ST_NO_SIGNAL = "no_signal"
ST_DISCONNECTED = "disconnected"
ST_ERROR = "error"
ST_STOPPED = "stopped"


@dataclass
class SourceSpec:
    device: DeviceInfo
    backend: str = "dshow"
    mode: VideoMode | None = None
    fps: float | None = None


class SyntheticCapture:
    """Fonte de vídeo simulada, usada APENAS em testes automatizados
    (habilitada pela variável CAPTUREPRO_TEST_SOURCE=1)."""

    def __init__(self, width=1920, height=1080, fps=30.0):
        self.w, self.h, self.fps = int(width), int(height), float(fps or 30)
        self.n = 0
        self.opened = True
        self.black = False
        self.fail = False
        yy, xx = np.mgrid[0:self.h, 0:self.w]
        base = np.zeros((self.h, self.w, 3), np.uint8)
        base[..., 0] = (xx * 255 // max(1, self.w - 1)).astype(np.uint8)
        base[..., 1] = (yy * 255 // max(1, self.h - 1)).astype(np.uint8)
        base[..., 2] = 128
        self.base = base
        self._t = time.monotonic()

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.opened or self.fail:
            time.sleep(0.05)
            return False, None
        dt = 1.0 / self.fps - (time.monotonic() - self._t)
        if dt > 0:
            time.sleep(dt)
        self._t = time.monotonic()
        self.n += 1
        if self.black:
            return True, np.zeros_like(self.base)
        f = self.base.copy()
        cx = int((self.n * 7) % self.w)
        cv2.circle(f, (cx, self.h // 2), max(10, self.h // 8), (255, 255, 255), -1)
        cv2.putText(f, f"{self.n}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
        return True, f

    def get(self, prop):
        return {cv2.CAP_PROP_FRAME_WIDTH: self.w, cv2.CAP_PROP_FRAME_HEIGHT: self.h,
                cv2.CAP_PROP_FPS: self.fps}.get(prop, 0.0)

    def set(self, prop, value):
        return False

    def release(self):
        self.opened = False


def fourcc_to_str(v: float) -> str | None:
    try:
        i = int(v)
        if i <= 0:
            return None
        s = "".join(chr((i >> (8 * k)) & 0xFF) for k in range(4))
        return s if all(32 <= ord(c) < 127 for c in s) else None
    except Exception:
        return None


def open_capture(spec: SourceSpec):
    """Abre o dispositivo e aplica o modo pedido. Retorna o objeto ou None."""
    dev = spec.device
    if dev.is_test:
        m = spec.mode
        return SyntheticCapture(m.width if m else 1920, m.height if m else 1080, spec.fps or 30)
    api = BACKENDS.get(spec.backend, BACKENDS["auto"])[1]
    if not devices.IS_WINDOWS and spec.backend in ("dshow", "msmf"):
        api = cv2.CAP_ANY
    cap = cv2.VideoCapture(dev.index, api)
    if not cap.isOpened():
        cap.release()
        return None
    m = spec.mode
    # Ordem importa no DirectShow: FPS → FOURCC → largura/altura
    if spec.fps:
        cap.set(cv2.CAP_PROP_FPS, float(spec.fps))
    if m:
        if m.fourcc and len(m.fourcc) == 4:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*m.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, m.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, m.height)
    return cap


class CaptureWorker(QThread):
    preview_ready = Signal(QImage, int, int)       # imagem da prévia, largura e altura reais
    state_changed = Signal(str, str)               # estado, mensagem
    opened = Signal(dict)                          # propriedades efetivas
    modes_probed = Signal(list)                    # resoluções detectadas por sondagem

    NO_SIGNAL_AFTER = 2.0     # s sem quadros → "sem sinal"
    REOPEN_AFTER = 6.0        # s sem quadros → tenta reabrir
    RETRY_INTERVAL = 2.0      # s entre tentativas quando desconectado

    def __init__(self, spec: SourceSpec, probe_modes: bool = False, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.probe_modes = probe_modes
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: np.ndarray | None = None
        self._latest_time = 0.0
        self._view = (960, 540)
        self._adj: dict = {}
        self._consumed = True
        self._want_settings = False
        self._state = None
        self.actual: dict = {}

    # ------------------------------------------------------- API (thread UI)
    def stop(self, wait_ms: int = 8000) -> None:
        self._stop.set()
        if not self.wait(wait_ms):
            log.error("Thread de captura não terminou a tempo")

    def set_view_size(self, w: int, h: int) -> None:
        self._view = (max(16, int(w)), max(16, int(h)))

    def set_adjustments(self, adj: dict) -> None:
        self._adj = dict(adj)

    def mark_consumed(self) -> None:
        self._consumed = True

    def open_driver_settings(self) -> None:
        self._want_settings = True

    def latest_frame(self) -> np.ndarray | None:
        """Cópia do último quadro real recebido (resolução nativa)."""
        with self._lock:
            if self._latest is None:
                return None
            return self._latest.copy()

    def latest_age(self) -> float:
        with self._lock:
            return time.monotonic() - self._latest_time if self._latest is not None else 1e9

    # --------------------------------------------------------- interno
    def _set_state(self, st: str, msg: str) -> None:
        if (st, msg) != self._state:
            self._state = (st, msg)
            self.state_changed.emit(st, msg)

    def _sleep(self, secs: float) -> None:
        self._stop.wait(secs)

    def _report_actual(self, cap) -> None:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        fourcc = fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC))
        self.actual = {"width": w, "height": h, "fps": fps, "fourcc": fourcc}
        self.opened.emit(dict(self.actual))

    def _probe(self, cap) -> None:
        """Sem lista do driver: testa resoluções comuns e mantém só as aceitas."""
        self._set_state(ST_CONNECTING, "Detectando resoluções suportadas pela placa…")
        found = []
        w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        for (w, h) in devices.PROBE_RESOLUTIONS:
            if self._stop.is_set():
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if (aw, ah) == (w, h):
                found.append({"width": w, "height": h, "fourcc": None})
        if w0 and h0 and all((d["width"], d["height"]) != (w0, h0) for d in found):
            found.append({"width": w0, "height": h0, "fourcc": None})
        m = self.spec.mode
        tw, th = (m.width, m.height) if m else (w0, h0)
        if tw and th:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, tw)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, th)
        found.sort(key=lambda d: -(d["width"] * d["height"]))
        self.modes_probed.emit(found)

    def _find_device(self) -> DeviceInfo | None:
        try:
            return devices.device_present(self.spec.device.key)
        except Exception as e:
            log.debug("Enumeração falhou: %s", e)
            return None

    def run(self) -> None:  # noqa: C901 — laço principal, propositalmente linear
        if devices.IS_WINDOWS:
            from . import dshow
            dshow.com_init_thread()
        cap = None
        last_ok = time.monotonic()
        last_open = 0.0
        black_count = 0
        frame_i = 0
        try:
            while not self._stop.is_set():
                # ---------------------------------------------- abrir
                if cap is None:
                    self._set_state(ST_CONNECTING, f"Conectando a {self.spec.device.name}…")
                    last_open = time.monotonic()
                    try:
                        cap = open_capture(self.spec)
                    except Exception as e:
                        log.exception("Erro ao abrir dispositivo")
                        cap = None
                        self._set_state(ST_ERROR, f"Erro do driver ao abrir a placa: {e}")
                    if cap is None:
                        if self._state and self._state[0] != ST_ERROR:
                            self._set_state(
                                ST_DISCONNECTED,
                                "Não foi possível abrir a placa. Verifique o cabo USB, se o driver do "
                                "fabricante está instalado e se outro programa está usando o dispositivo. "
                                "Tentando novamente…")
                        self._sleep(self.RETRY_INTERVAL)
                        found = self._find_device()
                        if found:
                            self.spec.device = found  # índice pode ter mudado
                        continue
                    if self.probe_modes:
                        self.probe_modes = False
                        try:
                            self._probe(cap)
                        except Exception as e:
                            log.warning("Sondagem falhou: %s", e)
                    self._report_actual(cap)
                    last_ok = time.monotonic()
                    black_count = 0

                # ------------------------------------- diálogo do driver
                if self._want_settings:
                    self._want_settings = False
                    try:
                        cap.set(cv2.CAP_PROP_SETTINGS, 1)
                    except Exception as e:
                        log.warning("Diálogo do driver indisponível: %s", e)

                # ---------------------------------------------- ler
                try:
                    ok, frame = cap.read()
                except Exception as e:
                    log.warning("Erro de leitura: %s", e)
                    ok, frame = False, None
                if self._stop.is_set():
                    break
                now = time.monotonic()

                if not ok or frame is None or frame.size == 0:
                    idle = now - last_ok
                    if idle > self.NO_SIGNAL_AFTER:
                        self._set_state(ST_NO_SIGNAL, "Sem sinal de vídeo. Verifique se o equipamento "
                                                      "está ligado e o cabo de vídeo conectado.")
                    if idle > self.REOPEN_AFTER and now - last_open > self.REOPEN_AFTER:
                        found = self._find_device()
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = None
                        if found is None:
                            self._set_state(ST_DISCONNECTED, "Placa de captura desconectada. "
                                                             "Aguardando reconexão…")
                            while not self._stop.is_set():
                                self._sleep(self.RETRY_INTERVAL)
                                found = self._find_device()
                                if found:
                                    break
                        if found:
                            self.spec.device = found
                        last_ok = time.monotonic()
                        continue
                    self._sleep(0.02)
                    continue

                frame = processing.ensure_bgr(frame)
                last_ok = now
                with self._lock:
                    self._latest = frame
                    self._latest_time = now
                frame_i += 1
                if frame_i % 10 == 1:
                    black_count = black_count + 1 if processing.is_black_frame(frame) else 0
                if black_count >= 3:
                    self._set_state(ST_NO_SIGNAL, "Sem sinal de vídeo (imagem preta). Verifique se o "
                                                  "equipamento está ligado e a entrada correta selecionada.")
                else:
                    h, w = frame.shape[:2]
                    fps = self.actual.get("fps") or 0
                    extra = f" · {fps:.0f} quadros/s" if fps > 0 else ""
                    self._set_state(ST_LIVE, f"Vídeo conectado · {w} × {h}{extra}")

                # ------------------------------------------- prévia
                if self._consumed:
                    vw, vh = self._view
                    try:
                        rgb = processing.make_preview(frame, vw, vh, self._adj)
                        rgb = np.ascontiguousarray(rgb)
                        ph, pw = rgb.shape[:2]
                        img = QImage(rgb.data, pw, ph, pw * 3, QImage.Format.Format_RGB888).copy()
                        self._consumed = False
                        self.preview_ready.emit(img, frame.shape[1], frame.shape[0])
                    except Exception as e:
                        log.warning("Falha na prévia: %s", e)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            self._set_state(ST_STOPPED, "Captura parada")
