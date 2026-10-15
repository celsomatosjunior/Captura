import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["CAPTUREPRO_TEST_SOURCE"] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from capturepro.ui.theme import QSS
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    return app


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    d = tmp_path / "cfg"
    monkeypatch.setenv("CAPTUREPRO_CONFIG_DIR", str(d))
    return d
