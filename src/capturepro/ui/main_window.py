"""Janela principal do Capture Pro."""
from __future__ import annotations

import datetime as _dt
import logging
import os

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_DISPLAY_NAME, __version__, autostart, devices, processing, storage
from ..capture import BACKENDS, ST_LIVE, CaptureWorker, SourceSpec
from ..devices import DeviceCaps, DeviceInfo, VideoMode
from ..settings import IMAGE_FORMATS, NEUTRAL_ADJUSTMENTS, OUTPUT_RESOLUTIONS, Settings
from .video_view import VideoView

log = logging.getLogger(__name__)

NO_DEVICE_MSG = ("Nenhuma placa de captura encontrada.\n\nConecte a placa e clique em "
                 "“Atualizar dispositivos”. Placas internas PCI/PCIe e alguns modelos USB "
                 "precisam do driver do fabricante instalado no Windows.")

ADJ_LABELS = [("brightness", "Brilho"), ("contrast", "Contraste"),
              ("saturation", "Saturação"), ("sharpness", "Nitidez")]


# ---------------------------------------------------------------- salvamento
class _SaveSignals(QObject):
    done = Signal(str, QImage)
    failed = Signal(str)


class SaveTask(QRunnable):
    """Processa e grava a foto fora da thread da interface."""

    def __init__(self, frame, crop, adj, target, folder, prefix, fmt, quality):
        super().__init__()
        self.frame, self.crop, self.adj, self.target = frame, crop, adj, target
        self.folder, self.prefix, self.fmt, self.quality = folder, prefix, fmt, quality
        self.signals = _SaveSignals()

    def run(self):
        try:
            img = processing.process_for_save(self.frame, self.crop, self.adj, self.target)
            path = storage.save_image(img, self.folder, self.prefix, self.fmt, self.quality)
            thumb_src = processing.make_preview(img, 480, 320, None)
            h, w = thumb_src.shape[:2]
            thumb = QImage(thumb_src.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
            self.signals.done.emit(path, thumb)
        except PermissionError:
            self.signals.failed.emit("Sem permissão para gravar na pasta escolhida. Escolha outra pasta.")
        except OSError as e:
            self.signals.failed.emit(f"Erro ao gravar o arquivo: {e.strerror or e}")
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao salvar")
            self.signals.failed.emit(f"Erro ao salvar a imagem: {e}")


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ------------------------------------------------------------- janela
class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        self.devices: list[DeviceInfo] = []
        self.current: DeviceInfo | None = None
        self.caps = DeviceCaps()
        self.worker: CaptureWorker | None = None
        self.session_count = 0
        self.last_saved_path: str | None = None
        self._loading = False
        self._fullscreen = False
        self._was_maximized = False
        self._saves_pending = 0
        self.save_pool = QThreadPool(self)
        self.save_pool.setMaxThreadCount(1)   # preserva a ordem das fotos

        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(600)
        self._persist_timer.timeout.connect(self._persist_now)

        self.setWindowTitle(f"{APP_DISPLAY_NAME}")
        self.setMinimumSize(1060, 680)
        self._build_ui()
        self._install_shortcuts()
        self._load_global_settings()
        self._restore_geometry()
        QTimer.singleShot(0, lambda: self.refresh_devices(initial=True))

    # ================================================================ UI
    def _build_ui(self) -> None:
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ------------------------------------------------ barra superior
        self.topbar = QFrame(objectName="topbar")
        tl = QGridLayout(self.topbar)
        tl.setContentsMargins(16, 10, 16, 10)
        tl.setHorizontalSpacing(12)
        tl.setVerticalSpacing(4)
        title = QLabel("CAPTURE PRO", objectName="title")
        sub = QLabel("Capturador de imagens", objectName="subtitle")
        tl.addWidget(title, 0, 0)
        tl.addWidget(sub, 1, 0)

        self.cb_device = QComboBox()
        self.cb_device.setMinimumWidth(230)
        self.cb_device.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cb_input = QComboBox()
        self.cb_input.setMinimumWidth(170)
        self.cb_input.setToolTip("Entrada física da placa (HDMI/SDI, RCA, S-Video...), quando o driver permite escolher.")
        self.cb_mode = QComboBox()
        self.cb_mode.setMinimumWidth(240)
        self.cb_mode.setToolTip("Somente os modos anunciados pela placa de captura.\n"
                                "Formatos 'sem compressão' (YUY2) oferecem a maior fidelidade.")
        self.cb_fps = QComboBox()
        self.cb_fps.setMinimumWidth(90)
        self.cb_backend = QComboBox()
        for key in (("dshow", "msmf") if devices.IS_WINDOWS else ("auto",)):
            self.cb_backend.addItem(BACKENDS[key][0], key)
        self.cb_backend.setToolTip("Tecnologia de captura do Windows. Use DirectShow (padrão); se a placa "
                                   "não abrir, experimente Media Foundation.")
        self.bt_refresh = QPushButton("⟳  Atualizar dispositivos")
        self.bt_driver = QPushButton("Propriedades do driver")
        self.bt_driver.setToolTip("Abre a janela de configuração do próprio driver da placa (DirectShow).")

        cols = [("Placa de captura", self.cb_device), ("Entrada de vídeo", self.cb_input),
                ("Resolução de entrada", self.cb_mode), ("Quadros/s", self.cb_fps),
                ("Motor de captura", self.cb_backend)]
        for i, (lbl, w) in enumerate(cols, start=1):
            l = QLabel(lbl, objectName="muted")
            tl.addWidget(l, 0, i)
            tl.addWidget(w, 1, i)
        tl.addWidget(self.bt_refresh, 1, len(cols) + 1)
        tl.addWidget(self.bt_driver, 1, len(cols) + 2)
        tl.setColumnStretch(0, 1)
        outer.addWidget(self.topbar)

        # ------------------------------------------------ meio
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.view = VideoView()
        middle.addWidget(self.view, 1)
        self.side = self._build_side_panel()
        middle.addWidget(self.side)
        outer.addLayout(middle, 1)

        # ------------------------------------------------ barra inferior
        self.bottombar = QFrame(objectName="bottombar")
        bl = QHBoxLayout(self.bottombar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(10)
        self.bt_area = QPushButton("DEFINIR ÁREA")
        self.bt_area.setCheckable(True)
        self.bt_area.setToolTip("Mostra a moldura: arraste para mover; cantos e bordas redimensionam.\n"
                                "Somente o interior da moldura é salvo.")
        self.bt_full = QPushButton("CAPTURAR TELA INTEIRA")
        self.bt_full.setToolTip("Remove o recorte e salva a imagem completa do vídeo.")
        self.bt_folder = QPushButton("ESCOLHER PASTA")
        self.bt_open = QPushButton("ABRIR PASTA")
        self.bt_reset = QPushButton("RESTAURAR AJUSTES")
        self.bt_fullscreen = QPushButton("TELA CHEIA (F11)")
        self.bt_save = QPushButton("SALVAR IMAGEM  (F8)", objectName="primary")
        self.bt_save.setMinimumHeight(52)
        self.bt_save.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        for b in (self.bt_area, self.bt_full, self.bt_folder, self.bt_open, self.bt_reset, self.bt_fullscreen):
            b.setMinimumHeight(44)
            bl.addWidget(b)
        bl.addStretch(1)
        bl.addWidget(self.bt_save)
        outer.addWidget(self.bottombar)

        self.statusBar().showMessage("Pronto")
        self.lb_status_right = QLabel(f"v{__version__}", objectName="muted")
        self.statusBar().addPermanentWidget(self.lb_status_right)

        # ------------------------------------------------ sinais
        self.cb_device.currentIndexChanged.connect(self._on_device_changed)
        self.cb_input.currentIndexChanged.connect(self._on_input_changed)
        self.cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.cb_fps.currentIndexChanged.connect(self._on_fps_changed)
        self.cb_backend.currentIndexChanged.connect(self._on_backend_changed)
        self.bt_refresh.clicked.connect(lambda: self.refresh_devices(initial=False))
        self.bt_driver.clicked.connect(self._open_driver_settings)
        self.bt_area.toggled.connect(self._toggle_area)
        self.bt_full.clicked.connect(self.full_image)
        self.bt_folder.clicked.connect(self.choose_folder)
        self.bt_open.clicked.connect(self.open_folder)
        self.bt_reset.clicked.connect(self.reset_adjustments)
        self.bt_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.bt_save.clicked.connect(self.save_image)
        self.view.crop_changed.connect(self._on_crop_changed)
        self.view.view_resized.connect(self._on_view_resized)

    def _build_side_panel(self) -> QWidget:
        frame = QFrame(objectName="sidepanel")
        frame.setFixedWidth(320)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fl.addWidget(scroll)
        inner = QWidget(objectName="sideinner")
        scroll.setWidget(inner)
        scroll.viewport().setObjectName("sideviewport")
        v = QVBoxLayout(inner)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(8)

        # ajustes
        v.addWidget(QLabel("Ajustes da imagem", objectName="section"))
        self.sliders: dict[str, QSlider] = {}
        self.slider_vals: dict[str, QLabel] = {}
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        for row, (key, label) in enumerate(ADJ_LABELS):
            lo, hi = processing.ADJ_RANGES[key]
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(lo, hi)
            s.setValue(0)
            s.setPageStep(10)
            val = QLabel("0", objectName="muted")
            val.setFixedWidth(34)
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            s.valueChanged.connect(lambda x, k=key: self._on_slider(k, x))
            s.setToolTip("Clique no nome do ajuste para zerar")
            name = ClickableLabel(label)
            name.setMinimumWidth(76)
            name.setToolTip("Clique para zerar este ajuste")
            name.clicked.connect(lambda k=key: self.sliders[k].setValue(0))
            g.addWidget(name, row, 0)
            g.addWidget(s, row, 1)
            g.addWidget(val, row, 2)
            self.sliders[key] = s
            self.slider_vals[key] = val
        v.addLayout(g)
        note = QLabel("Os ajustes aparecem na prévia e são aplicados à foto salva. "
                      "Em zero, a imagem é salva sem nenhuma alteração.", objectName="muted")
        note.setWordWrap(True)
        v.addWidget(note)

        # imagem salva
        v.addSpacing(6)
        v.addWidget(QLabel("Imagem salva", objectName="section"))
        v.addWidget(QLabel("Resolução da fotografia", objectName="muted"))
        self.cb_outres = QComboBox()
        for key, label in OUTPUT_RESOLUTIONS:
            self.cb_outres.addItem(label, key)
        v.addWidget(self.cb_outres)
        custom = QHBoxLayout()
        self.sp_w = QSpinBox()
        self.sp_w.setRange(16, 16384)
        self.sp_w.setSuffix(" px")
        self.sp_h = QSpinBox()
        self.sp_h.setRange(16, 16384)
        self.sp_h.setSuffix(" px")
        self.lb_x = QLabel("×")
        custom.addWidget(self.sp_w)
        custom.addWidget(self.lb_x)
        custom.addWidget(self.sp_h)
        self.custom_row = QWidget()
        self.custom_row.setLayout(custom)
        custom.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.custom_row)
        self.lb_outinfo = QLabel("", objectName="muted")
        self.lb_outinfo.setWordWrap(True)
        v.addWidget(self.lb_outinfo)

        v.addWidget(QLabel("Formato", objectName="muted"))
        self.cb_format = QComboBox()
        for key, label in IMAGE_FORMATS:
            self.cb_format.addItem(label, key)
        v.addWidget(self.cb_format)
        self.jpeg_row = QWidget()
        jr = QHBoxLayout(self.jpeg_row)
        jr.setContentsMargins(0, 0, 0, 0)
        jr.addWidget(QLabel("Qualidade JPEG", objectName="muted"))
        self.sl_quality = QSlider(Qt.Orientation.Horizontal)
        self.sl_quality.setRange(50, 100)
        self.lb_quality = QLabel("95", objectName="muted")
        self.lb_quality.setFixedWidth(28)
        jr.addWidget(self.sl_quality, 1)
        jr.addWidget(self.lb_quality)
        v.addWidget(self.jpeg_row)

        v.addWidget(QLabel("Nome do arquivo (prefixo)", objectName="muted"))
        self.ed_prefix = QLineEdit()
        self.ed_prefix.setMaxLength(60)
        v.addWidget(self.ed_prefix)
        self.lb_example = QLabel("", objectName="muted")
        self.lb_example.setWordWrap(True)
        v.addWidget(self.lb_example)

        v.addWidget(QLabel("Pasta de destino", objectName="muted"))
        self.lb_folder = QLabel("")
        self.lb_folder.setWordWrap(True)
        self.lb_folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.lb_folder)

        # última foto e contador
        v.addSpacing(6)
        v.addWidget(QLabel("Última imagem salva", objectName="section"))
        self.thumb_frame = QFrame(objectName="thumbframe")
        tfl = QVBoxLayout(self.thumb_frame)
        tfl.setContentsMargins(4, 4, 4, 4)
        self.lb_thumb = ClickableLabel("Nenhuma imagem salva ainda")
        self.lb_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lb_thumb.setMinimumHeight(150)
        self.lb_thumb.setObjectName("muted")
        self.lb_thumb.setToolTip("Clique para abrir a imagem")
        self.lb_thumb.clicked.connect(self._open_last)
        tfl.addWidget(self.lb_thumb)
        v.addWidget(self.thumb_frame)
        self.lb_lastname = QLabel("", objectName="muted")
        self.lb_lastname.setWordWrap(True)
        v.addWidget(self.lb_lastname)
        cnt = QHBoxLayout()
        self.lb_counter = QLabel("0", objectName="counter")
        cnt.addWidget(self.lb_counter)
        cl = QVBoxLayout()
        cl.addWidget(QLabel("fotos nesta sessão", objectName="muted"))
        self.lb_today = QLabel("", objectName="muted")
        cl.addWidget(self.lb_today)
        cnt.addLayout(cl, 1)
        v.addLayout(cnt)

        v.addSpacing(6)
        self.ck_autostart = QCheckBox("Iniciar com o Windows")
        self.ck_autostart.setEnabled(autostart.supported())
        v.addWidget(self.ck_autostart)
        v.addStretch(1)

        self.cb_outres.currentIndexChanged.connect(self._on_outres_changed)
        self.sp_w.valueChanged.connect(self._on_custom_res)
        self.sp_h.valueChanged.connect(self._on_custom_res)
        self.cb_format.currentIndexChanged.connect(self._on_format_changed)
        self.sl_quality.valueChanged.connect(self._on_quality)
        self.ed_prefix.textChanged.connect(self._on_prefix)
        self.ck_autostart.toggled.connect(self._on_autostart)
        return frame

    def _install_shortcuts(self) -> None:
        def sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ShortcutContext.ApplicationShortcut)
            s.activated.connect(fn)
            return s
        self.sc_save = sc(Qt.Key.Key_F8, self.save_image)
        self.sc_full = sc(Qt.Key.Key_F11, self.toggle_fullscreen)
        self.sc_esc = sc(Qt.Key.Key_Escape, self._on_escape)

    # ========================================================= settings
    def _load_global_settings(self) -> None:
        s = self.settings
        self._loading = True
        try:
            self._set_combo_data(self.cb_backend, s.get("backend"))
            self._set_combo_data(self.cb_outres, s.get("output_resolution"))
            self.sp_w.setValue(int(s.get("custom_width") or 1920))
            self.sp_h.setValue(int(s.get("custom_height") or 1080))
            self._set_combo_data(self.cb_format, s.get("format"))
            self.sl_quality.setValue(int(s.get("jpeg_quality") or 95))
            self.lb_quality.setText(str(self.sl_quality.value()))
            self.ed_prefix.setText(s.get("prefix") or "CAPTURA")
            want = bool(s.get("autostart"))
            if autostart.supported():
                want = autostart.is_enabled()
            self.ck_autostart.setChecked(want)
        finally:
            self._loading = False
        self.custom_row.setVisible(self.cb_outres.currentData() == "custom")
        self.jpeg_row.setVisible(self.cb_format.currentData() == "jpeg")
        self._update_folder_label()
        self._update_example()
        self._update_output_info()

    def _restore_geometry(self) -> None:
        geo = self.settings.get("window_geometry")
        if geo and isinstance(geo, list) and len(geo) == 4:
            x, y, w, h = geo
            self.setGeometry(int(x), int(y), max(int(w), 1060), max(int(h), 680))
            # garante que a janela está visível em algum monitor
            screen = QApplication.screenAt(self.geometry().center())
            if screen is None:
                self.resize(1280, 800)
                self.move(40, 40)
        else:
            self.resize(1360, 860)
        self._start_maximized = bool(self.settings.get("window_maximized"))

    def _persist_device(self) -> None:
        if not self.current:
            return
        self.settings.update_device(
            self.current.key,
            mode=self.cb_mode.currentData(),
            fps=self.cb_fps.currentData(),
            crop=self.view.crop(),
            adjustments=self.adjustments(),
            input=self.cb_input.currentData(),
        )

    def _schedule_persist(self) -> None:
        if not self._loading:
            self._persist_timer.start()

    def _persist_now(self) -> None:
        self._persist_device()
        self.settings.save()

    # ========================================================= helpers
    @staticmethod
    def _set_combo_data(cb: QComboBox, data) -> bool:
        for i in range(cb.count()):
            if cb.itemData(i) == data:
                cb.setCurrentIndex(i)
                return True
        return False

    def adjustments(self) -> dict:
        return {k: s.value() for k, s in self.sliders.items()}

    def output_folder(self) -> str:
        return self.settings.get("output_folder")

    def output_target(self):
        return processing.parse_resolution(self.cb_outres.currentData(), self.sp_w.value(), self.sp_h.value())

    def _update_folder_label(self) -> None:
        self.lb_folder.setText(self.output_folder())
        self._update_today()

    def _update_today(self) -> None:
        n = storage.count_today(self.output_folder(), self.ed_prefix.text())
        self.lb_today.setText(f"hoje nesta pasta: {n}")

    def _update_example(self) -> None:
        fmt = self.cb_format.currentData() or "png"
        pre = self.ed_prefix.text()
        date = storage.date_string()
        n = storage.next_number(self.output_folder(), pre, date)
        self.lb_example.setText("Próximo arquivo: " + storage.build_name(pre, date, n, fmt))

    def _update_output_info(self) -> None:
        sw, sh = self.view.source_size()
        if not sw or not sh:
            self.lb_outinfo.setText("")
            return
        x0, y0, x1, y1 = processing.crop_to_pixels(sw, sh, self.view.crop())
        cw, ch = x1 - x0, y1 - y0
        ow, oh, up = processing.output_size(cw, ch, self.output_target())
        area = "área definida" if self.view.crop() else "imagem inteira"
        txt = f"Foto final: {ow} × {oh} px ({area}, origem {cw} × {ch} px)."
        if up:
            txt = (f"⚠ A saída ({ow} × {oh}) é maior que a resolução real ({cw} × {ch}). "
                   f"A imagem será ampliada por interpolação, sem ganho de detalhe.")
            self.lb_outinfo.setObjectName("warn")
        else:
            self.lb_outinfo.setObjectName("muted")
        self.lb_outinfo.setText(txt)
        self.lb_outinfo.style().unpolish(self.lb_outinfo)
        self.lb_outinfo.style().polish(self.lb_outinfo)

    # ========================================================= dispositivos
    def refresh_devices(self, initial: bool = False) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            found = devices.list_devices()
        except Exception as e:  # noqa: BLE001
            log.exception("Falha na enumeração")
            found = []
            self.statusBar().showMessage(f"Erro ao listar dispositivos: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.devices = found
        cur_key = self.current.key if self.current else self.settings.get("last_device")
        self._loading = True
        try:
            self.cb_device.clear()
            for d in found:
                self.cb_device.addItem(d.name, d.key)
            idx = next((i for i, d in enumerate(found) if d.key == cur_key), 0 if found else -1)
            self.cb_device.setCurrentIndex(idx)
        finally:
            self._loading = False
        n = len(found)
        self.statusBar().showMessage(f"{n} dispositivo(s) de vídeo encontrado(s)" if n else "Nenhum dispositivo encontrado")
        if not found:
            self._stop_capture()
            self.current = None
            self.view.clear_frame()
            self.view.set_status("stopped", NO_DEVICE_MSG)
            self._enable_device_controls(False)
            return
        self._enable_device_controls(True)
        newdev = found[idx]
        running_same = (self.current is not None and self.current.key == newdev.key
                        and self.worker is not None and self.worker.isRunning())
        if running_same:
            self.current = newdev
            return
        self._select_device(newdev)

    def _enable_device_controls(self, on: bool) -> None:
        for w in (self.cb_device, self.cb_mode, self.bt_driver):
            w.setEnabled(on)
        if not on:
            self.cb_input.setEnabled(False)
            self.cb_fps.setEnabled(False)
        self.bt_driver.setEnabled(on and self.cb_backend.currentData() == "dshow"
                                  and not (self.current and self.current.is_test))

    def _on_device_changed(self, idx: int) -> None:
        if self._loading or idx < 0 or idx >= len(self.devices):
            return
        self._select_device(self.devices[idx])

    def _select_device(self, dev: DeviceInfo) -> None:
        if self.current is not None:
            self._persist_device()
        self._stop_capture()
        self.current = dev
        self.settings.set("last_device", dev.key)
        self.view.clear_frame()
        self.view.set_status("connecting", f"Lendo recursos de {dev.name}…")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.caps = devices.query_caps(dev)
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao consultar recursos")
            self.caps = DeviceCaps()
            self.statusBar().showMessage(f"O driver não informou os recursos da placa: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        ds = self.settings.device(dev.key)
        self._loading = True
        try:
            self._populate_inputs(ds.get("input"))
            self._populate_modes(ds.get("mode"), ds.get("probed_modes"))
            self._populate_fps(ds.get("fps"))
            for k, s in self.sliders.items():
                s.setValue(int(ds["adjustments"].get(k, 0)))
                self.slider_vals[k].setText(str(s.value()))
            self.view.set_crop(ds.get("crop"))
        finally:
            self._loading = False
        self.bt_area.setChecked(False)
        self.bt_driver.setEnabled(self.cb_backend.currentData() == "dshow" and not dev.is_test)
        # roteia a entrada escolhida ANTES de abrir o vídeo
        self._apply_input_route()
        self._start_capture()

    def _populate_inputs(self, saved) -> None:
        self.cb_input.clear()
        self.cb_input.addItem("Padrão do driver", None)
        for inp in self.caps.inputs:
            mark = "  (atual)" if inp["pin"] == self.caps.current_input else ""
            self.cb_input.addItem(inp["label"] + mark, inp["pin"])
        self.cb_input.setEnabled(bool(self.caps.inputs))
        if saved is not None:
            self._set_combo_data(self.cb_input, saved)

    def _populate_modes(self, saved, probed) -> None:
        self.cb_mode.clear()
        self.cb_mode.addItem("Padrão da placa", None)
        modes = list(self.caps.modes)
        if not modes and probed:
            modes = [VideoMode.from_dict(d) for d in probed]
        self._mode_objs = modes
        for m in modes:
            self.cb_mode.addItem(m.label(), m.to_dict())
        if saved:
            for i in range(1, self.cb_mode.count()):
                d = self.cb_mode.itemData(i)
                if (d["width"], d["height"], d.get("fourcc")) == (saved.get("width"), saved.get("height"), saved.get("fourcc")):
                    self.cb_mode.setCurrentIndex(i)
                    break
        self._need_probe = not modes and not (self.current and self.current.is_test)

    def _populate_fps(self, saved) -> None:
        self.cb_fps.clear()
        self.cb_fps.addItem("Padrão", None)
        d = self.cb_mode.currentData()
        opts = VideoMode.from_dict(d).fps_options() if d else []
        for f in opts:
            self.cb_fps.addItem(f"{f:g}", float(f))
        self.cb_fps.setEnabled(bool(opts))
        if saved:
            for i in range(1, self.cb_fps.count()):
                if abs(self.cb_fps.itemData(i) - float(saved)) < 0.02:
                    self.cb_fps.setCurrentIndex(i)
                    break

    def _apply_input_route(self) -> None:
        pin = self.cb_input.currentData()
        if pin is None or not self.current:
            return
        inp = next((i for i in self.caps.inputs if i["pin"] == pin), None)
        if inp and not devices.route_input(self.current, inp):
            self.statusBar().showMessage("O driver não aceitou a troca de entrada; usando a entrada atual.")

    def _current_mode(self) -> VideoMode | None:
        d = self.cb_mode.currentData()
        return VideoMode.from_dict(d) if d else None

    # ========================================================= captura
    def _start_capture(self) -> None:
        if not self.current:
            return
        spec = SourceSpec(self.current, self.cb_backend.currentData() or "auto",
                          self._current_mode(), self.cb_fps.currentData())
        w = CaptureWorker(spec, probe_modes=getattr(self, "_need_probe", False), parent=self)
        self._need_probe = False
        w.preview_ready.connect(self._on_preview)
        w.state_changed.connect(self._on_state)
        w.opened.connect(self._on_opened)
        w.modes_probed.connect(self._on_modes_probed)
        dpr = self.view.devicePixelRatioF()
        w.set_view_size(int(self.view.width() * dpr), int(self.view.height() * dpr))
        w.set_adjustments(self.adjustments())
        self.worker = w
        w.start()

    def _stop_capture(self) -> None:
        w = self.worker
        self.worker = None
        if w is not None:
            for sig in (w.preview_ready, w.state_changed, w.opened, w.modes_probed):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                w.stop()
            finally:
                QApplication.restoreOverrideCursor()
            w.deleteLater()

    def _restart_capture(self) -> None:
        self._persist_device()
        self._stop_capture()
        self.view.set_status("connecting", "Reconfigurando a captura…")
        self._start_capture()

    def _on_preview(self, img: QImage, w: int, h: int) -> None:
        if self.sender() is not self.worker:
            return
        old = self.view.source_size()
        self.view.set_frame(img, w, h)
        if self.worker:
            self.worker.mark_consumed()
        if old != (w, h):
            self._update_output_info()

    def _on_state(self, state: str, msg: str) -> None:
        if self.sender() is not self.worker:
            return
        self.view.set_status(state, msg)
        self.statusBar().showMessage(msg)

    def _on_opened(self, actual: dict) -> None:
        m = self._current_mode()
        if m and (actual.get("width"), actual.get("height")) != (m.width, m.height) and actual.get("width"):
            self.view.show_toast(f"A placa entregou {actual['width']} × {actual['height']} "
                                 f"em vez de {m.width} × {m.height}", ok=False, ms=4500)

    def _on_modes_probed(self, found: list) -> None:
        if not self.current:
            return
        self.settings.update_device(self.current.key, probed_modes=found)
        self.settings.save()
        cur = self.cb_mode.currentData()
        self._loading = True
        try:
            self._populate_modes(cur, found)
            self._populate_fps(self.cb_fps.currentData())
        finally:
            self._loading = False
        self.statusBar().showMessage(f"{len(found)} resolução(ões) aceitas pela placa")

    def _on_input_changed(self, _i: int) -> None:
        if self._loading or not self.current:
            return
        self._persist_device()
        self._stop_capture()
        self._apply_input_route()
        self._start_capture()

    def _on_mode_changed(self, _i: int) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            self._populate_fps(None)
        finally:
            self._loading = False
        self._restart_capture()

    def _on_fps_changed(self, _i: int) -> None:
        if not self._loading:
            self._restart_capture()

    def _on_backend_changed(self, _i: int) -> None:
        if self._loading:
            return
        self.settings.set("backend", self.cb_backend.currentData())
        self.settings.save()
        self.bt_driver.setEnabled(self.cb_backend.currentData() == "dshow"
                                  and bool(self.current) and not self.current.is_test)
        if self.current:
            self._restart_capture()

    def _open_driver_settings(self) -> None:
        if self.worker:
            self.worker.open_driver_settings()

    def _on_view_resized(self, w: int, h: int) -> None:
        if self.worker:
            self.worker.set_view_size(w, h)

    # ========================================================= área
    def _toggle_area(self, on: bool) -> None:
        self.view.set_edit_mode(on)
        self.bt_area.setText("CONCLUIR ÁREA" if on else "DEFINIR ÁREA")
        if on:
            self.view.show_toast("Arraste a moldura; use cantos e bordas para redimensionar", ok=True, ms=3500)
        self._update_output_info()

    def full_image(self) -> None:
        self.bt_area.setChecked(False)
        self.view.set_crop(None)
        self._on_crop_changed(None)
        self.view.show_toast("Recorte removido: será salva a imagem inteira")

    def _on_crop_changed(self, _crop) -> None:
        self._update_output_info()
        self._schedule_persist()

    # ========================================================= ajustes
    def _on_slider(self, key: str, value: int) -> None:
        self.slider_vals[key].setText(str(value))
        if self.worker:
            self.worker.set_adjustments(self.adjustments())
        self._schedule_persist()

    def reset_adjustments(self) -> None:
        for k, s in self.sliders.items():
            s.setValue(NEUTRAL_ADJUSTMENTS[k])
        self.view.show_toast("Ajustes restaurados para os valores neutros")

    # ========================================================= saída
    def _on_outres_changed(self, _i: int) -> None:
        self.custom_row.setVisible(self.cb_outres.currentData() == "custom")
        if self._loading:
            return
        self.settings.set("output_resolution", self.cb_outres.currentData())
        self.settings.save()
        self._update_output_info()

    def _on_custom_res(self, _v: int) -> None:
        if self._loading:
            return
        self.settings.set("custom_width", self.sp_w.value())
        self.settings.set("custom_height", self.sp_h.value())
        self._persist_timer.start()
        self._update_output_info()

    def _on_format_changed(self, _i: int) -> None:
        self.jpeg_row.setVisible(self.cb_format.currentData() == "jpeg")
        if self._loading:
            return
        self.settings.set("format", self.cb_format.currentData())
        self.settings.save()
        self._update_example()

    def _on_quality(self, v: int) -> None:
        self.lb_quality.setText(str(v))
        if not self._loading:
            self.settings.set("jpeg_quality", v)
            self._persist_timer.start()

    def _on_prefix(self, text: str) -> None:
        clean = storage.sanitize_prefix(text)
        if not self._loading:
            self.settings.set("prefix", clean)
            self._persist_timer.start()
        self._update_example()
        self._update_today()

    def _on_autostart(self, on: bool) -> None:
        if self._loading:
            return
        ok = autostart.set_enabled(on)
        if not ok and autostart.supported():
            QMessageBox.warning(self, APP_DISPLAY_NAME, "Não foi possível alterar a inicialização automática.")
        self.settings.set("autostart", on)
        self.settings.save()

    def choose_folder(self) -> None:
        start = self.output_folder()
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Escolher pasta de destino", start)
        if not path:
            return
        path = os.path.normpath(path)
        test = os.path.join(path, ".capturepro_teste_escrita")
        try:
            with open(test, "wb") as f:
                f.write(b"ok")
            os.remove(test)
        except OSError:
            QMessageBox.warning(self, APP_DISPLAY_NAME, "Não é possível gravar nessa pasta. Escolha outra.")
            return
        self.settings.set("output_folder", path)
        self.settings.save()
        self._update_folder_label()
        self._update_example()
        self.view.show_toast(f"Pasta de destino: {path}")

    def open_folder(self) -> None:
        folder = self.output_folder()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_last(self) -> None:
        if self.last_saved_path and os.path.exists(self.last_saved_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_saved_path))

    # ========================================================= salvar
    def save_image(self) -> None:
        if not self.worker:
            self.view.show_toast("Nenhuma placa de captura ativa", ok=False)
            return
        if self.worker.latest_age() > 3.0:
            self.view.show_toast("Sem imagem de vídeo para salvar (sem sinal)", ok=False)
            return
        frame = self.worker.latest_frame()
        if frame is None:
            self.view.show_toast("Ainda não há imagem de vídeo", ok=False)
            return
        task = SaveTask(frame, self.view.crop(), self.adjustments(), self.output_target(),
                        self.output_folder(), self.ed_prefix.text(), self.cb_format.currentData() or "png",
                        self.sl_quality.value())
        task.signals.done.connect(self._on_saved)
        task.signals.failed.connect(self._on_save_failed)
        self._saves_pending += 1
        self.save_pool.start(task)

    def _on_saved(self, path: str, thumb: QImage) -> None:
        self._saves_pending = max(0, self._saves_pending - 1)
        self.session_count += 1
        self.last_saved_path = path
        self.lb_counter.setText(str(self.session_count))
        pm = QPixmap.fromImage(thumb).scaled(QSize(280, 180), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        self.lb_thumb.setPixmap(pm)
        self.lb_lastname.setText(os.path.basename(path))
        self.view.show_toast(f"✓ Imagem salva: {os.path.basename(path)}")
        self.statusBar().showMessage(f"Salvo em {path}")
        self._update_example()
        self._update_today()

    def _on_save_failed(self, msg: str) -> None:
        self._saves_pending = max(0, self._saves_pending - 1)
        self.view.show_toast(msg, ok=False, ms=5000)
        self.statusBar().showMessage(msg)

    # ========================================================= tela cheia
    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self.exit_fullscreen()
        else:
            self._was_maximized = self.isMaximized()
            self._fullscreen = True
            for w in (self.topbar, self.bottombar, self.side):
                w.hide()
            self.statusBar().hide()
            self.showFullScreen()
            self.view.show_toast("Tela cheia · F8 salva · ESC sai", ms=3000)

    def exit_fullscreen(self) -> None:
        if not self._fullscreen:
            return
        self._fullscreen = False
        for w in (self.topbar, self.bottombar, self.side):
            w.show()
        self.statusBar().show()
        if self._was_maximized:
            self.showMaximized()
        else:
            self.showNormal()

    def _on_escape(self) -> None:
        if self._fullscreen:
            self.exit_fullscreen()
        elif self.bt_area.isChecked():
            self.bt_area.setChecked(False)

    # ========================================================= fechar
    def closeEvent(self, ev: QCloseEvent) -> None:
        if self._fullscreen:
            self.exit_fullscreen()
        self._persist_timer.stop()
        self._persist_device()
        if not self.isMaximized():
            g = self.geometry()
            self.settings.set("window_geometry", [g.x(), g.y(), g.width(), g.height()])
        self.settings.set("window_maximized", self.isMaximized())
        self.settings.save()
        self._stop_capture()
        self.save_pool.waitForDone(10000)   # termina gravações pendentes
        super().closeEvent(ev)
