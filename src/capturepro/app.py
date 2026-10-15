"""Ponto de entrada do Capture Pro."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import traceback

from . import APP_DISPLAY_NAME, APP_NAME, __version__
from .settings import config_dir

log = logging.getLogger("capturepro")


def _setup_logging() -> str:
    path = os.path.join(config_dir(), "capturepro.log")
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        root.addHandler(logging.StreamHandler(sys.stderr))
    return path


def _resource(*parts: str) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "resources", *parts)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    log_path = _setup_logging()
    log.info("Iniciando %s %s (Python %s)", APP_DISPLAY_NAME, __version__, sys.version.split()[0])

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CapturePro.CapturePro.1")
        except Exception:
            pass

    from PySide6.QtCore import QLockFile, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    from PySide6.QtCore import QLibraryInfo, QTranslator
    translator = QTranslator(app)
    if translator.load("qtbase_pt_BR", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    icon_path = _resource("icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    def excepthook(etype, value, tb):
        msg = "".join(traceback.format_exception(etype, value, tb))
        log.error("Erro não tratado:\n%s", msg)
        try:
            QMessageBox.critical(None, APP_DISPLAY_NAME,
                                 f"Ocorreu um erro inesperado:\n\n{value}\n\nDetalhes em:\n{log_path}")
        except Exception:
            pass
    sys.excepthook = excepthook

    # uma única instância (duas instâncias disputariam a mesma placa)
    lock = QLockFile(os.path.join(config_dir(), "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_DISPLAY_NAME, "O Capture Pro já está aberto.")
        return 0

    from .ui.main_window import MainWindow
    from .ui.theme import QSS
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    win = MainWindow()
    if getattr(win, "_start_maximized", False):
        win.showMaximized()
    else:
        win.show()
    code = app.exec()
    lock.unlock()
    log.info("Encerrado (código %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
