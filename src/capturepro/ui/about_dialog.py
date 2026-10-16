"""(2.0) Janela "Sobre o Capture Pro"."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

ABOUT_PARAGRAPHS = [
    "Sistema de captura de imagens para Windows.",
    "<b>Idealização e autoria: Dr. Celso Matos Junior</b>",
    "Médico com mais de 20 anos de experiência profissional, desenvolveu o Capture Pro a partir "
    "da necessidade de uma ferramenta de captura de imagens simples, versátil e eficiente.",
    "Ao longo de sua experiência com documentação de imagens médicas, percebeu que os sistemas "
    "disponíveis nem sempre atendiam às suas necessidades.",
    "Entusiasta de tecnologia e videogames, idealizou uma solução que pudesse ser utilizada tanto "
    "na área médica quanto em outras situações de captura de vídeo e imagem.",
    "O Capture Pro nasceu da combinação entre experiência profissional, tecnologia e busca por praticidade.",
]


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aboutdlg")
        self.setWindowTitle("Sobre o Capture Pro")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedWidth(480)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 18)
        v.setSpacing(10)
        title = QLabel("Capture Pro 2.0", objectName="abouttitle")
        v.addWidget(title)
        for text in ABOUT_PARAGRAPHS:
            lb = QLabel(text)
            lb.setWordWrap(True)
            lb.setTextFormat(Qt.TextFormat.RichText)
            v.addWidget(lb)
        foot = QLabel("Versão 2.0 — 2026", objectName="muted")
        v.addSpacing(4)
        v.addWidget(foot)
        row = QHBoxLayout()
        row.addStretch(1)
        self.bt_close = QPushButton("FECHAR")
        self.bt_close.setDefault(True)
        self.bt_close.clicked.connect(self.accept)
        row.addWidget(self.bt_close)
        v.addLayout(row)
