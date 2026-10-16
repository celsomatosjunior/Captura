"""Testes das alterações da versão 2.0 (opções contextuais de área, janela Sobre)."""
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

from capturepro.capture import ST_LIVE
from capturepro.settings import Settings
from test_ui import load, pump, saved_files, wait_saved, win  # noqa: F401  (fixture reutilizada)


def _positions(w):
    btns = (w.bt_area, w.bt_full, w.bt_folder, w.bt_open, w.bt_reset, w.bt_fullscreen, w.bt_save)
    return [(b.geometry().x(), b.geometry().y(), b.width(), b.height()) for b in btns]


def test_context_options_hidden_outside_edit_mode(qapp, win):
    assert win.area_options.isHidden()
    win.bt_area.click()                                   # DEFINIR ÁREA
    assert win.view.edit_mode()
    assert win.area_options.isVisible()
    assert win.bt_area.text() == "CONCLUIR ÁREA"          # botão original inalterado
    win.bt_area.click()                                   # CONCLUIR ÁREA continua funcionando
    assert not win.view.edit_mode()
    assert win.area_options.isHidden()
    assert win.bt_area.text() == "DEFINIR ÁREA"
    # ESC também encerra a edição e esconde as opções
    win.bt_area.click()
    win.sc_esc.activated.emit()
    assert win.area_options.isHidden() and not win.view.edit_mode()


def test_other_buttons_do_not_move(qapp, win):
    """Em modo de edição, mostrar as opções contextuais não move nenhum botão em
    relação ao comportamento da 1.0 (mesmo modo de edição, sem as opções)."""
    win.bt_area.click()
    pump(qapp, timeout=0.3)
    with_options = _positions(win)
    win.area_options.setVisible(False)
    pump(qapp, timeout=0.3)
    assert _positions(win) == with_options, "as opções contextuais não podem deslocar os botões"
    win.bt_area.click()
    pump(qapp, timeout=0.3)
    normal = _positions(win)
    assert win.area_options.isHidden()
    win.bt_area.click()
    win.bt_area.click()
    pump(qapp, timeout=0.3)
    assert _positions(win) == normal


def test_save_area_persists_and_crops(qapp, win):
    win.bt_area.click()
    win.view.set_crop([0.25, 0.25, 0.5, 0.5])
    win.view.crop_changed.emit(win.view.crop())
    win.bt_area_save.click()
    assert not win.view.edit_mode()
    assert win.area_options.isHidden()
    assert win.view.crop() == [0.25, 0.25, 0.5, 0.5]       # continua marcada
    # gravado imediatamente no arquivo de configuração (mecanismo existente)
    assert Settings().device(win.current.key)["crop"] == [0.25, 0.25, 0.5, 0.5]
    win.save_image()
    wait_saved(qapp, win, 1)
    assert load(win, saved_files(win)[0]).shape[:2] == (540, 960)   # só o interior


def test_save_area_survives_restart(qapp, cfg, tmp_path):
    from capturepro.ui.main_window import MainWindow
    w = MainWindow(Settings())
    w.show()
    assert pump(qapp, lambda: w.view._state == ST_LIVE)
    w.bt_area.click()
    w.view.set_crop([0.1, 0.2, 0.3, 0.4])
    w.bt_area_save.click()
    w.close()
    pump(qapp, timeout=0.2)
    w2 = MainWindow(Settings())
    w2.show()
    assert pump(qapp, lambda: w2.view._state == ST_LIVE)
    try:
        assert w2.view.crop() == pytest.approx([0.1, 0.2, 0.3, 0.4])
        assert w2.area_options.isHidden()
    finally:
        w2.close()
        pump(qapp, timeout=0.2)


def test_remove_selection_returns_to_full_frame(qapp, win):
    win.view.set_crop([0.1, 0.1, 0.2, 0.2])
    win.bt_area.click()
    win.bt_area_remove.click()
    assert win.view.crop() is None
    assert not win.view.edit_mode()
    assert win.area_options.isHidden()
    assert Settings().device(win.current.key)["crop"] is None
    win.save_image()
    wait_saved(qapp, win, 1)
    assert load(win, saved_files(win)[0]).shape[:2] == (1080, 1920)


def test_remove_selection_survives_restart(qapp, cfg):
    from capturepro.ui.main_window import MainWindow
    s = Settings()
    s.update_device("__teste__", crop=[0.2, 0.2, 0.3, 0.3])
    s.save()
    w = MainWindow(Settings())
    w.show()
    assert pump(qapp, lambda: w.view._state == ST_LIVE)
    assert w.view.crop() is not None
    w.bt_area.click()
    w.bt_area_remove.click()
    w.close()
    pump(qapp, timeout=0.2)
    w2 = MainWindow(Settings())
    w2.show()
    assert pump(qapp, lambda: w2.view._state == ST_LIVE)
    try:
        assert w2.view.crop() is None
    finally:
        w2.close()
        pump(qapp, timeout=0.2)


def test_full_image_button_still_works(qapp, win):
    win.view.set_crop([0.1, 0.1, 0.2, 0.2])
    win.bt_full.click()
    assert win.view.crop() is None and not win.bt_full.isHidden()


def test_about_dialog_opens_and_closes(qapp, win):
    from capturepro.ui.about_dialog import AboutDialog
    seen = {}

    def inspect_and_close():
        dlg = QApplication.activeModalWidget()
        seen["dlg"] = dlg
        if isinstance(dlg, AboutDialog):
            seen["title"] = dlg.windowTitle()
            seen["labels"] = " ".join(l.text() for l in dlg.findChildren(QLabel))
            dlg.bt_close.click()

    before = win.geometry()
    QTimer.singleShot(200, inspect_and_close)
    win.bt_about.click()                      # bloqueia até FECHAR
    assert isinstance(seen.get("dlg"), AboutDialog)
    assert seen["title"] == "Sobre o Capture Pro"
    assert "Capture Pro 2.0" in seen["labels"]
    assert "Dr. Celso Matos Junior" in seen["labels"]
    assert "Versão 2.0 — 2026" in seen["labels"]
    assert QApplication.activeModalWidget() is None
    assert win.geometry() == before


def test_version_is_2():
    from capturepro import __version__
    assert __version__ == "2.0.0"


def test_v1_config_is_read_unchanged(qapp, cfg):
    """Arquivo de configuração no formato da 1.0 é lido sem migração e sem perdas."""
    import json
    import os
    from capturepro.ui.main_window import MainWindow
    os.makedirs(cfg, exist_ok=True)
    v1 = {"version": 1, "last_device": "__teste__", "prefix": "ULTRASSOM", "format": "jpeg",
          "devices": {"__teste__": {"crop": [0.12, 0.08, 0.7, 0.8],
                                    "adjustments": {"brightness": 3, "contrast": 0, "saturation": 0, "sharpness": 0}}}}
    (cfg / "config.json").write_text(json.dumps(v1), encoding="utf-8")
    w = MainWindow(Settings())
    w.show()
    assert pump(qapp, lambda: w.view._state == ST_LIVE)
    try:
        assert w.view.crop() == pytest.approx([0.12, 0.08, 0.7, 0.8])
        assert w.ed_prefix.text() == "ULTRASSOM" and w.cb_format.currentData() == "jpeg"
        assert w.sliders["brightness"].value() == 3
    finally:
        w.close()
        pump(qapp, timeout=0.2)


def test_installer_script_is_single_file():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nsi = open(os.path.join(root, "build", "installer.nsi"), encoding="utf-8").read()
    assert "parte2" not in nsi and "/x cv2" not in nsi and "ExecWait" not in nsi
    assert 'File /r "${DISTDIR}\\*.*"' in nsi
    sh = open(os.path.join(root, "build", "build.sh"), encoding="utf-8").read()
    assert "installer_part2.nsi" not in sh
