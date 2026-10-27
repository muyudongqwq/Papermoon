"""Graphics items used by the visual map canvas."""

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
)


class LocationItem(QGraphicsRectItem):
    WIDTH = 112
    HEIGHT = 58

    def __init__(self, record, moved_callback):
        super().__init__(-self.WIDTH / 2, -self.HEIGHT / 2, self.WIDTH, self.HEIGHT)
        self.location_id = record.location_id
        self.key = f"location:{record.location_id}"
        self._moved_callback = moved_callback
        self._setting_position = True
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        self.label = QGraphicsSimpleTextItem(self)
        self.label.setFont(QFont("Microsoft YaHei UI", 9))
        self.update_record(record)
        self.setPos(record.x, record.y)
        self._setting_position = False

    def update_record(self, record):
        suffix = []
        if record.is_building:
            suffix.append("建筑")
        if record.high_level:
            suffix.append("高层")
        if record.is_port:
            suffix.append("码头")
        text = record.name + (f"\n[{' / '.join(suffix)}]" if suffix else "")
        self.label.setText(text)
        bounds = self.label.boundingRect()
        self.label.setPos(-bounds.width() / 2, -bounds.height() / 2)
        self.setToolTip(text)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._setting_position:
            self._moved_callback(self.location_id, value)
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        painter.setPen(QPen(QColor("#d97706" if selected else "#334155"), 2.5 if selected else 1.5))
        painter.setBrush(QBrush(QColor("#fef3c7" if selected else "#f8fafc")))
        painter.drawRoundedRect(self.rect(), 9, 9)


class RoadItem(QGraphicsPathItem):
    def __init__(self, record, location_items):
        super().__init__()
        self.road_id = record.road_id
        self.key = f"road:{record.road_id}"
        self.location_items = location_items
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(-1)
        # A wide invisible pen makes the road easier to click; paint() draws the visible line.
        self.setPen(QPen(QColor(0, 0, 0, 0), 12))
        self.update_geometry()

    def update_geometry(self):
        points = [item.pos() for item in self.location_items]
        if not points:
            self.setPath(QPainterPath())
            return
        center = QPointF(
            sum(point.x() for point in points) / len(points),
            sum(point.y() for point in points) / len(points),
        )
        path = QPainterPath()
        for point in points:
            path.moveTo(center)
            path.lineTo(point)
        path.addEllipse(QRectF(center.x() - 6, center.y() - 6, 12, 12))
        self.setPath(path)
        self.update()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        painter.setPen(QPen(QColor("#ea580c" if selected else "#64748b"), 4 if selected else 3))
        painter.setBrush(QBrush(QColor("#fb923c" if selected else "#94a3b8")))
        painter.drawPath(self.path())

