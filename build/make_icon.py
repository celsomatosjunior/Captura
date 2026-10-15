"""Gera o ícone do aplicativo (PNG + ICO) desenhando com Qt."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPen, QBrush
from PIL import Image

app = QGuiApplication(sys.argv)
S = 512
img = QImage(S, S, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
g = QLinearGradient(0, 0, 0, S)
g.setColorAt(0, QColor(31, 41, 55)); g.setColorAt(1, QColor(12, 16, 22))
p.setBrush(g); p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(16, 16, S-32, S-32), 96, 96)
# lente
p.setBrush(QColor(46, 204, 113)); p.drawEllipse(QPointF(S/2, S/2), 118, 118)
p.setBrush(QColor(12, 16, 22)); p.drawEllipse(QPointF(S/2, S/2), 78, 78)
p.setBrush(QColor(46, 204, 113, 200)); p.drawEllipse(QPointF(S/2 - 22, S/2 - 22), 22, 22)
# cantos de recorte
pen = QPen(QColor(236, 240, 241), 30); pen.setCapStyle(Qt.PenCapStyle.RoundCap); p.setPen(pen)
a, b, L = 92, S - 92, 86
for (x, y, dx, dy) in [(a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)]:
    p.drawLine(QPointF(x, y), QPointF(x + dx * L, y)); p.drawLine(QPointF(x, y), QPointF(x, y + dy * L))
p.end()
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
png = os.path.join(out, "icon.png"); img.save(png)
Image.open(png).save(os.path.join(out, "icon.ico"), sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print("ok")
