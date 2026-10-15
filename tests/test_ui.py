"""Testes da interface com a fonte de vídeo simulada (sem hardware real).

Validam: botões, prévia, recorte persistente, salvamento, tela cheia, atalhos,
troca de resolução/entrada, reconexão e persistência das configurações.
"""
import os
import time

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from capturepro.capture import ST_LIVE
from capturepro.settings import Settings


def pump(app, cond=None, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return cond() if cond else True


@pytest.fixture
def win(qapp, cfg, tmp_path):
    from capturepro.ui.main_window import MainWindow
    s = Settings()
    s.set("output_folder", str(tmp_path / "out"))
    s.save()
    w = MainWindow(s)
    w.resize(1400, 860)
    w.show()
    assert pump(qapp, lambda: w.view._state == ST_LIVE and w.view._img is not None), "vídeo não iniciou"
    yield w
    w.close()
    pump(qapp, timeout=0.2)


def saved_files(w):
    folder = w.output_folder()
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def wait_saved(app, w, n):
    assert pump(app, lambda: len(saved_files(w)) >= n and w._saves_pending == 0), "imagem não foi salva"


def load(w, name):
    return cv2.imdecode(np.fromfile(os.path.join(w.output_folder(), name), np.uint8), cv2.IMREAD_COLOR)


def drag(view, a: QPointF, b: QPointF):
    def ev(t, p, btn, btns):
        return QMouseEvent(t, p, view.mapToGlobal(p.toPoint()).toPointF(), btn, btns, Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
    for p in (mid, b):
        view.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, p, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    view.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))


def test_device_listed_and_live(win):
    assert win.cb_device.count() >= 1
    assert win.view.source_size() == (1920, 1080)
    assert win.worker.latest_frame().shape == (1080, 1920, 3)


def test_save_full_frame_png(qapp, win):
    win.bt_save.click()
    wait_saved(qapp, win, 1)
    files = saved_files(win)
    assert files[0].endswith("_001.png")
    assert load(win, files[0]).shape == (1080, 1920, 3)
    assert win.lb_counter.text() == "1"
    assert win.lb_thumb.pixmap() is not None and not win.lb_thumb.pixmap().isNull()


def test_define_area_by_mouse_and_save_only_inside(qapp, win):
    win.bt_area.click()
    assert win.view.edit_mode() and win.view.crop() is not None
    ir = win.view.image_rect()
    # novo retângulo desenhado fora da moldura atual (canto superior esquerdo)
    a = QPointF(ir.x() + ir.width() * 0.02, ir.y() + ir.height() * 0.03)
    b = QPointF(ir.x() + ir.width() * 0.08, ir.y() + ir.height() * 0.06)
    drag(win.view, a, b)
    c = win.view.crop()
    assert c[0] < 0.1 and c[2] > 0.03
    # move a moldura arrastando por dentro
    cr = win.view._crop_widget_rect()
    before = win.view.crop()
    drag(win.view, cr.center(), cr.center() + QPointF(ir.width() * 0.2, ir.height() * 0.2))
    after = win.view.crop()
    assert after[0] > before[0] + 0.15 and abs(after[2] - before[2]) < 1e-9
    # redimensiona pelo canto inferior direito
    cr = win.view._crop_widget_rect()
    drag(win.view, cr.bottomRight(), cr.bottomRight() + QPointF(ir.width() * 0.1, ir.height() * 0.1))
    resized = win.view.crop()
    assert resized[2] > after[2] + 0.08
    win.bt_area.click()                      # concluir
    assert not win.view.edit_mode() and win.view.crop() == resized
    frame = win.worker.latest_frame()
    win.save_image()
    wait_saved(qapp, win, 1)
    out = load(win, saved_files(win)[0])
    x0 = round(resized[0] * 1920); x1 = round((resized[0] + resized[2]) * 1920)
    y0 = round(resized[1] * 1080); y1 = round((resized[1] + resized[3]) * 1080)
    assert out.shape[:2] == (y1 - y0, x1 - x0), "salva exatamente a área, em pixels reais"
    # sem moldura verde desenhada na foto: as bordas da foto vêm do vídeo
    assert not np.all(out[0, :, 1] > 180) or not np.all(out[0, :, 0] < 140)
    del frame


def test_crop_independent_of_window_size(qapp, win):
    win.view.set_crop([0.25, 0.25, 0.5, 0.5])
    win._on_crop_changed(None)
    win.resize(1100, 700)
    pump(qapp, timeout=0.5)
    assert win.view.crop() == [0.25, 0.25, 0.5, 0.5]
    win.save_image()
    wait_saved(qapp, win, 1)
    assert load(win, saved_files(win)[0]).shape[:2] == (540, 960)


def test_full_image_button_removes_crop(qapp, win):
    win.view.set_crop([0.1, 0.1, 0.2, 0.2])
    win.bt_full.click()
    assert win.view.crop() is None
    win.save_image()
    wait_saved(qapp, win, 1)
    assert load(win, saved_files(win)[0]).shape[:2] == (1080, 1920)


@pytest.mark.parametrize("fmt,ext", [("jpeg", ".jpg"), ("bmp", ".bmp"), ("png", ".png")])
def test_formats_via_ui(qapp, win, fmt, ext):
    win._set_combo_data(win.cb_format, fmt)
    assert win.jpeg_row.isHidden() == (fmt != "jpeg")
    win.save_image()
    wait_saved(qapp, win, 1)
    assert saved_files(win)[0].endswith(ext)


def test_output_resolution_and_upscale_warning(qapp, win):
    win._set_combo_data(win.cb_outres, "1280x720")
    win.save_image()
    wait_saved(qapp, win, 1)
    assert load(win, saved_files(win)[0]).shape[:2] == (720, 1280)
    win.view.set_crop([0, 0, 0.25, 0.25])          # 480×270 real
    win._on_crop_changed(None)
    assert "interpolação" in win.lb_outinfo.text()
    win._set_combo_data(win.cb_outres, "custom")
    assert not win.custom_row.isHidden()


def test_adjustments_applied_and_reset(qapp, win):
    win.sliders["brightness"].setValue(60)
    win.save_image()
    wait_saved(qapp, win, 1)
    adj = load(win, saved_files(win)[0])
    win.bt_reset.click()
    assert all(s.value() == 0 for s in win.sliders.values())
    win.save_image()
    wait_saved(qapp, win, 2)
    neutral = load(win, saved_files(win)[1])
    assert adj.mean() > neutral.mean() + 20


def test_sequential_and_prefix(qapp, win):
    win.ed_prefix.setText("ENDOSCOPIA")
    for i in range(3):
        win.save_image()
    wait_saved(qapp, win, 3)
    names = saved_files(win)
    assert [n.rsplit("_", 1)[1] for n in names] == ["001.png", "002.png", "003.png"]
    assert all(n.startswith("ENDOSCOPIA_") for n in names)
    assert win.lb_counter.text() == "3"


def test_choose_and_open_folder(qapp, win, tmp_path, monkeypatch):
    target = tmp_path / "Endoscopia"
    target.mkdir()
    from capturepro.ui import main_window as mw
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(target)))
    opened = []
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    win.bt_folder.click()
    assert win.output_folder() == str(target)
    win.bt_open.click()
    assert opened and os.path.normpath(opened[0]) == str(target)
    win.save_image()
    wait_saved(qapp, win, 1)
    assert len(os.listdir(target)) == 1


def test_fullscreen_and_shortcuts(qapp, win):
    win.sc_full.activated.emit()
    pump(qapp, timeout=0.3)
    assert win._fullscreen and win.topbar.isHidden() and win.side.isHidden()
    win.sc_save.activated.emit()             # F8 em tela cheia
    wait_saved(qapp, win, 1)
    win.sc_esc.activated.emit()
    pump(qapp, timeout=0.3)
    assert not win._fullscreen and not win.topbar.isHidden()
    win.bt_fullscreen.click()
    assert win._fullscreen
    win.toggle_fullscreen()
    assert not win._fullscreen
    # as teclas estão registradas corretamente
    assert win.sc_save.key().toString() == "F8"
    assert win.sc_full.key().toString() == "F11"
    assert win.sc_esc.key().toString() == "Esc"


def test_change_input_resolution_and_fps(qapp, win):
    # 1280×720 do modo simulado
    idx = next(i for i in range(win.cb_mode.count())
               if win.cb_mode.itemData(i) and win.cb_mode.itemData(i)["width"] == 1280)
    win.cb_mode.setCurrentIndex(idx)
    assert pump(qapp, lambda: win.view.source_size() == (1280, 720) and win.view._state == ST_LIVE)
    assert win.cb_fps.isEnabled() and win.cb_fps.count() > 1
    win.cb_fps.setCurrentIndex(1)
    assert pump(qapp, lambda: win.view._state == ST_LIVE and win.worker.actual.get("fps", 0) > 0)
    win.cb_input.setCurrentIndex(2)
    assert pump(qapp, lambda: win.view._state == ST_LIVE)
    win.bt_refresh.click()
    assert pump(qapp, lambda: win.view._state == ST_LIVE)


def test_settings_persist_after_restart(qapp, cfg, tmp_path):
    from capturepro.ui.main_window import MainWindow
    s = Settings()
    s.set("output_folder", str(tmp_path / "pasta"))
    w = MainWindow(s)
    w.show()
    assert pump(qapp, lambda: w.view._state == ST_LIVE)
    w.view.set_crop([0.2, 0.3, 0.4, 0.5])
    w._on_crop_changed(None)
    w.sliders["contrast"].setValue(12)
    w._set_combo_data(w.cb_format, "jpeg")
    w.ed_prefix.setText("EXAME")
    w.close()
    pump(qapp, timeout=0.3)

    w2 = MainWindow(Settings())
    w2.show()
    assert pump(qapp, lambda: w2.view._state == ST_LIVE)
    try:
        assert w2.view.crop() == pytest.approx([0.2, 0.3, 0.4, 0.5])
        assert w2.sliders["contrast"].value() == 12
        assert w2.cb_format.currentData() == "jpeg"
        assert w2.ed_prefix.text() == "EXAME"
        assert w2.output_folder() == str(tmp_path / "pasta")
        assert w2.current.key == "__teste__"
    finally:
        w2.close()
        pump(qapp, timeout=0.2)


def test_reconnect_after_signal_loss(qapp, win, monkeypatch):
    from capturepro import capture
    w = win.worker
    monkeypatch.setattr(capture.CaptureWorker, "NO_SIGNAL_AFTER", 0.3)
    monkeypatch.setattr(capture.CaptureWorker, "REOPEN_AFTER", 1.0)
    w.NO_SIGNAL_AFTER, w.REOPEN_AFTER = 0.3, 1.0
    states = []
    w.state_changed.connect(lambda s, m: states.append(s))
    # simula cabo desconectado: o objeto de captura atual passa a falhar
    import gc
    caps = [o for o in gc.get_objects() if isinstance(o, capture.SyntheticCapture) and o.opened]
    assert caps
    for c in caps:
        c.fail = True
    assert pump(qapp, lambda: "no_signal" in states, timeout=5), states
    assert pump(qapp, lambda: states and states[-1] == ST_LIVE, timeout=8), states
    assert "connecting" in states


def test_black_frames_show_no_signal(qapp, win):
    from capturepro import capture
    import gc
    for c in [o for o in gc.get_objects() if isinstance(o, capture.SyntheticCapture) and o.opened]:
        c.black = True
    assert pump(qapp, lambda: win.view._state == "no_signal", timeout=6)
    win.save_image()   # ainda permitido: salva o quadro atual (preto)


def test_no_devices_message(qapp, cfg, monkeypatch):
    from capturepro.ui.main_window import MainWindow
    monkeypatch.setenv("CAPTUREPRO_TEST_SOURCE", "0")
    from capturepro import devices
    monkeypatch.setattr(devices, "list_devices", lambda: [])
    w = MainWindow(Settings())
    w.show()
    pump(qapp, timeout=0.5)
    try:
        assert w.current is None and "Nenhuma placa" in w.view._message
        w.save_image()   # não pode quebrar
        assert not w.cb_mode.isEnabled()
    finally:
        w.close()
