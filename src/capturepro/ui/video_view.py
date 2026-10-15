"""Widget de prévia ao vivo com moldura de recorte ajustável.

O recorte é guardado em coordenadas NORMALIZADAS da imagem (0..1), por isso
continua correto com qualquer tamanho de janela e é convertido para pixels
reais do vídeo apenas no momento de salvar. A moldura só é desenhada na tela.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..processing import crop_to_pixels

ACCENT = QColor(46, 204, 113)
HANDLE = 9          # tamanho do quadradinho
GRAB = 10           # tolerância do mouse (px)
MIN_NORM = 0.02     # tamanho mínimo da área (2% da imagem)

STATE_COLORS = {
    "live": QColor(46, 204, 113),
    "connecting": QColor(241, 196, 15),
    "no_signal": QColor(243, 156, 18),
    "disconnected": QColor(231, 76, 60),
    "error": QColor(231, 76, 60),
    "stopped": QColor(127, 140, 141),
}

_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor, "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor, "bl": Qt.CursorShape.SizeBDiagCursor,
    "t": Qt.CursorShape.SizeVerCursor, "b": Qt.CursorShape.SizeVerCursor,
    "l": Qt.CursorShape.SizeHorCursor, "r": Qt.CursorShape.SizeHorCursor,
    "move": Qt.CursorShape.SizeAllCursor, "new": Qt.CursorShape.CrossCursor,
}


class VideoView(QWidget):
    crop_changed = Signal(object)      # [x, y, w, h] normalizado, ou None
    view_resized = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._img: QImage | None = None
        self._src_w = 0
        self._src_h = 0
        self._crop: QRectF | None = None
        self._edit = False
        self._drag: tuple | None = None
        self._state = "stopped"
        self._message = "Nenhuma placa de captura selecionada"
        self._toast: tuple[str, bool] | None = None
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)

    # ------------------------------------------------------------ API
    def set_frame(self, img: QImage, src_w: int, src_h: int) -> None:
        self._img = img
        self._src_w, self._src_h = src_w, src_h
        self.update()

    def clear_frame(self) -> None:
        self._img = None
        self.update()

    def source_size(self) -> tuple[int, int]:
        return self._src_w, self._src_h

    def set_status(self, state: str, message: str) -> None:
        self._state, self._message = state, message
        self.update()

    def crop(self) -> list | None:
        if self._crop is None:
            return None
        r = self._crop
        return [r.x(), r.y(), r.width(), r.height()]

    def set_crop(self, crop) -> None:
        self._crop = QRectF(*crop) if crop else None
        self.update()

    def edit_mode(self) -> bool:
        return self._edit

    def set_edit_mode(self, on: bool) -> None:
        self._edit = bool(on)
        if self._edit and self._crop is None:
            self._crop = QRectF(0.1, 0.1, 0.8, 0.8)
            self.crop_changed.emit(self.crop())
        if not self._edit:
            self._drag = None
            self.unsetCursor()
        self.update()

    def show_toast(self, text: str, ok: bool = True, ms: int = 2500) -> None:
        self._toast = (text, ok)
        self._toast_timer.start(ms)
        self.update()

    def _clear_toast(self) -> None:
        self._toast = None
        self.update()

    # ------------------------------------------------------- geometria
    def image_rect(self) -> QRectF:
        sw = self._src_w or (self._img.width() if self._img else 0)
        sh = self._src_h or (self._img.height() if self._img else 0)
        W, H = self.width(), self.height()
        if sw <= 0 or sh <= 0 or W <= 0 or H <= 0:
            return QRectF()
        scale = min(W / sw, H / sh)
        w, h = sw * scale, sh * scale
        return QRectF((W - w) / 2.0, (H - h) / 2.0, w, h)

    def _crop_widget_rect(self) -> QRectF:
        ir = self.image_rect()
        r = self._crop
        if r is None or ir.isEmpty():
            return QRectF()
        return QRectF(ir.x() + r.x() * ir.width(), ir.y() + r.y() * ir.height(),
                      r.width() * ir.width(), r.height() * ir.height())

    def _to_norm(self, p: QPointF) -> QPointF:
        ir = self.image_rect()
        if ir.isEmpty():
            return QPointF(0, 0)
        return QPointF((p.x() - ir.x()) / ir.width(), (p.y() - ir.y()) / ir.height())

    def _hit(self, p: QPointF) -> str | None:
        ir = self.image_rect()
        if ir.isEmpty():
            return None
        cr = self._crop_widget_rect()
        if not cr.isEmpty():
            x, y = p.x(), p.y()
            l, t, r, b = cr.left(), cr.top(), cr.right(), cr.bottom()
            # em molduras pequenas, a tolerância diminui para o centro continuar "mover"
            gx = max(3.0, min(GRAB, cr.width() / 4))
            gy = max(3.0, min(GRAB, cr.height() / 4))
            near_l, near_r = abs(x - l) <= gx, abs(x - r) <= gx
            near_t, near_b = abs(y - t) <= gy, abs(y - b) <= gy
            in_x = l - gx <= x <= r + gx
            in_y = t - gy <= y <= b + gy
            if near_t and near_l:
                return "tl"
            if near_t and near_r:
                return "tr"
            if near_b and near_l:
                return "bl"
            if near_b and near_r:
                return "br"
            if near_t and in_x:
                return "t"
            if near_b and in_x:
                return "b"
            if near_l and in_y:
                return "l"
            if near_r and in_y:
                return "r"
            if cr.contains(p):
                return "move"
        if ir.contains(p):
            return "new"
        return None

    # ---------------------------------------------------------- mouse
    def mousePressEvent(self, ev):
        if not self._edit or ev.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(ev)
        p = ev.position()
        part = self._hit(p)
        if part is None:
            return
        start = self._to_norm(p)
        if part == "new":
            start.setX(min(max(start.x(), 0.0), 1.0))
            start.setY(min(max(start.y(), 0.0), 1.0))
            self._crop = QRectF(start.x(), start.y(), 0.0, 0.0)
            part = "br"
        self._drag = (part, start, QRectF(self._crop))
        self.setCursor(_CURSORS.get(part, Qt.CursorShape.ArrowCursor))
        self.update()

    def mouseMoveEvent(self, ev):
        p = ev.position()
        if not self._edit:
            return super().mouseMoveEvent(ev)
        if self._drag is None:
            part = self._hit(p)
            if part:
                self.setCursor(_CURSORS[part])
            else:
                self.unsetCursor()
            return
        part, start, r0 = self._drag
        cur = self._to_norm(p)
        dx, dy = cur.x() - start.x(), cur.y() - start.y()
        if part == "move":
            x = min(max(r0.x() + dx, 0.0), 1.0 - r0.width())
            y = min(max(r0.y() + dy, 0.0), 1.0 - r0.height())
            self._crop = QRectF(x, y, r0.width(), r0.height())
        else:
            l, t, r, b = r0.left(), r0.top(), r0.right(), r0.bottom()
            if "l" in part:
                l += dx
            if "r" in part:
                r += dx
            if "t" in part:
                t += dy
            if "b" in part:
                b += dy
            l, r = sorted((min(max(l, 0.0), 1.0), min(max(r, 0.0), 1.0)))
            t, b = sorted((min(max(t, 0.0), 1.0), min(max(b, 0.0), 1.0)))
            self._crop = QRectF(l, t, r - l, b - t)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag is None:
            return super().mouseReleaseEvent(ev)
        self._drag = None
        r = self._crop
        if r is not None and (r.width() < MIN_NORM or r.height() < MIN_NORM):
            # clique sem arrastar: mantém a área anterior ou cria uma mínima
            w = max(r.width(), MIN_NORM * 5)
            h = max(r.height(), MIN_NORM * 5)
            x = min(max(r.x(), 0.0), 1.0 - w)
            y = min(max(r.y(), 0.0), 1.0 - h)
            self._crop = QRectF(x, y, w, h)
        self.crop_changed.emit(self.crop())
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        dpr = self.devicePixelRatioF()
        self.view_resized.emit(int(self.width() * dpr), int(self.height() * dpr))

    # ---------------------------------------------------------- pintura
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(11, 13, 17))
        ir = self.image_rect()
        if self._img is not None and not ir.isEmpty():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(ir, self._img)
            if self._crop is not None:
                self._paint_crop(p, ir)
            if self._state not in ("live", "stopped"):
                self._paint_center_message(p, self._message, translucent=True)
        else:
            self._paint_center_message(p, self._message, translucent=False)
        self._paint_badge(p)
        if self._toast:
            self._paint_toast(p)
        p.end()

    def _paint_crop(self, p: QPainter, ir: QRectF) -> None:
        cr = self._crop_widget_rect()
        outside = QPainterPath()
        outside.addRect(ir)
        inner = QPainterPath()
        inner.addRect(cr)
        p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 115))
        pen = QPen(ACCENT, 2)
        pen.setCosmetic(True)
        if not self._edit:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(cr)
        if self._edit:
            p.setBrush(ACCENT)
            p.setPen(QPen(QColor(10, 10, 10), 1))
            hs = HANDLE
            for pt in (cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight(),
                       QPointF(cr.center().x(), cr.top()), QPointF(cr.center().x(), cr.bottom()),
                       QPointF(cr.left(), cr.center().y()), QPointF(cr.right(), cr.center().y())):
                p.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))
        # dimensões reais em pixels
        if self._src_w and self._src_h:
            x0, y0, x1, y1 = crop_to_pixels(self._src_w, self._src_h, self.crop())
            txt = f"{x1 - x0} × {y1 - y0} px"
            f = QFont(self.font())
            f.setPointSizeF(max(8.0, f.pointSizeF() - 0.5))
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 12
            th = fm.height() + 6
            tx = cr.left()
            ty = cr.top() - th - 4 if cr.top() - th - 4 > ir.top() else cr.top() + 4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(QRectF(tx, ty, tw, th), 4, 4)
            p.setPen(ACCENT)
            p.drawText(QRectF(tx, ty, tw, th), Qt.AlignmentFlag.AlignCenter, txt)

    def _paint_center_message(self, p: QPainter, text: str, translucent: bool) -> None:
        if not text:
            return
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 2)
        p.setFont(f)
        box_w = min(self.width() - 40, 560)
        rect = QRectF((self.width() - box_w) / 2, 0, box_w, self.height())
        br = p.fontMetrics().boundingRect(rect.toRect(), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter, text)
        box = QRectF(br).adjusted(-18, -14, 18, 14)
        if translucent:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 175))
            p.drawRoundedRect(box, 10, 10)
        p.setPen(QColor(220, 225, 232))
        p.drawText(rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter, text)

    def _paint_badge(self, p: QPainter) -> None:
        labels = {"live": "AO VIVO", "connecting": "CONECTANDO", "no_signal": "SEM SINAL",
                  "disconnected": "DESCONECTADO", "error": "ERRO", "stopped": "PARADO"}
        txt = labels.get(self._state, self._state.upper())
        if self._state == "live" and self._crop is not None:
            txt += "  ·  ÁREA DEFINIDA"
        if self._edit:
            txt += "  ·  AJUSTANDO ÁREA"
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(8.0, f.pointSizeF() - 1))
        p.setFont(f)
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(txt) + 34
        h = fm.height() + 10
        r = QRectF(12, 12, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setBrush(STATE_COLORS.get(self._state, QColor(150, 150, 150)))
        p.drawEllipse(QPointF(r.left() + 13, r.center().y()), 5, 5)
        p.setPen(QColor(235, 238, 242))
        p.drawText(r.adjusted(24, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)

    def _paint_toast(self, p: QPainter) -> None:
        text, ok = self._toast
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() + 1)
        p.setFont(f)
        fm = p.fontMetrics()
        w = min(fm.horizontalAdvance(text) + 36, self.width() - 24)
        h = fm.height() + 16
        r = QRectF((self.width() - w) / 2, self.height() - h - 18, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(22, 120, 66, 225) if ok else QColor(160, 40, 40, 230))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(QColor(255, 255, 255))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                   fm.elidedText(text, Qt.TextElideMode.ElideMiddle, int(w - 20)))
