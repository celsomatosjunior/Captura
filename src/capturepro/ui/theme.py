"""Tema visual escuro (adequado a salas de exame com pouca luz)."""

QSS = """
* { font-family: "Segoe UI", "Noto Sans", Arial; font-size: 10pt; }
QMainWindow, QWidget#root { background: #14171c; color: #e6e9ee; }
QWidget { color: #e6e9ee; }
QLabel#title { font-size: 15pt; font-weight: 700; color: #ffffff; }
QLabel#subtitle { color: #8b95a3; }
QLabel#section { font-size: 10pt; font-weight: 700; color: #ffffff; padding-top: 6px; }
QLabel#muted, QLabel.muted { color: #8b95a3; }
QLabel#warn { color: #f5b041; }
QLabel#counter { font-size: 18pt; font-weight: 700; color: #2ecc71; }
QFrame#topbar, QFrame#bottombar { background: #1b1f26; border-bottom: 1px solid #262b34; }
QFrame#bottombar { border-top: 1px solid #262b34; border-bottom: none; }
QFrame#sidepanel { background: #1b1f26; border-left: 1px solid #262b34; }
QWidget#sideinner, QWidget#sideviewport { background: #1b1f26; }
QFrame#thumbframe { background: #0f1115; border: 1px solid #2b313b; border-radius: 6px; }
QComboBox, QLineEdit, QSpinBox {
  background: #232832; border: 1px solid #333a46; border-radius: 6px;
  padding: 5px 8px; min-height: 22px; selection-background-color: #2ecc71; selection-color: #0b0d11;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover { border-color: #46505f; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color: #2ecc71; }
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled { color: #626b78; background: #1d2129; }
QComboBox QAbstractItemView { background: #232832; border: 1px solid #333a46; selection-background-color: #2b6e4a; }
QPushButton {
  background: #262c36; border: 1px solid #343c49; border-radius: 8px;
  padding: 8px 14px; color: #e6e9ee; font-weight: 600;
}
QPushButton:hover { background: #2e3540; border-color: #4a5463; }
QPushButton:pressed { background: #1f242c; }
QPushButton:disabled { color: #5c6470; background: #1e222a; border-color: #2a2f38; }
QPushButton:checked { background: #1f5c3c; border-color: #2ecc71; color: #ffffff; }
QPushButton#primary {
  background: #27ae60; border: 1px solid #2ecc71; color: #ffffff;
  font-size: 13pt; font-weight: 800; padding: 12px 26px; border-radius: 10px;
}
QPushButton#primary:hover { background: #2ecc71; }
QPushButton#primary:pressed { background: #1e8a4c; }
QPushButton#primary:disabled { background: #22412f; border-color: #2a5a3e; color: #8fb5a0; }
QPushButton#link { background: transparent; border: none; color: #2ecc71; padding: 4px; text-align: left; }
QPushButton#link:hover { color: #58d68d; text-decoration: underline; }
QSlider::groove:horizontal { height: 4px; background: #333a46; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2ecc71; border-radius: 2px; }
QSlider::handle:horizontal { background: #e6e9ee; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid #4a5463; background: #232832; }
QCheckBox::indicator:checked { background: #2ecc71; border-color: #2ecc71; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #333a46; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QStatusBar { background: #101317; color: #8b95a3; }
QToolTip { background: #232832; color: #e6e9ee; border: 1px solid #46505f; padding: 4px; }
"""
