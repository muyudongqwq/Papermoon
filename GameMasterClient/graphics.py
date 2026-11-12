"""Read-only map rendering shared by setup, placement and live game pages."""

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsScene, QGraphicsSimpleTextItem


class ReadOnlyMapScene(QGraphicsScene):
    def __init__(self, document=None, parent=None):
        super().__init__(parent)
        self.document = None
        self.location_points = {}
        if document is not None:
            self.set_document(document)

    def set_document(self, document):
        self.clear()
        self.document = document
        self.location_points = {
            key: QPointF(record.x, record.y)
            for key, record in document.locations.items()
        }
        for road in document.roads.values():
            points = [self.location_points[key] for key in road.location_ids]
            center = QPointF(
                sum(point.x() for point in points) / len(points),
                sum(point.y() for point in points) / len(points),
            )
            for point in points:
                self.addLine(center.x(), center.y(), point.x(), point.y(), QPen(QColor("#64748b"), 3))
            self.addEllipse(center.x() - 4, center.y() - 4, 8, 8,
                            QPen(QColor("#64748b")), QBrush(QColor("#94a3b8")))
        for key, record in document.locations.items():
            point = self.location_points[key]
            rectangle = self.addRect(QRectF(point.x() - 56, point.y() - 29, 112, 58),
                                     QPen(QColor("#334155"), 1.5), QBrush(QColor("#f8fafc")))
            rectangle.setToolTip(record.name)
            suffix = []
            if record.is_building:
                suffix.append("建筑")
            if record.high_level:
                suffix.append("高层")
            if record.is_port:
                suffix.append("码头")
            label = QGraphicsSimpleTextItem(record.name + (f"\n[{' / '.join(suffix)}]" if suffix else ""))
            label.setFont(QFont("Microsoft YaHei UI", 9))
            bounds = label.boundingRect()
            label.setPos(point.x() - bounds.width() / 2, point.y() - bounds.height() / 2)
            self.addItem(label)
        self.setSceneRect(self.itemsBoundingRect().adjusted(-80, -80, 80, 80))

    def show_characters(self, characters, location_ids):
        """Draw compact actor markers. ``location_ids`` maps runtime positions to editor IDs."""
        offsets = {}
        for actor in characters:
            location_id = location_ids.get(actor.position)
            point = self.location_points.get(location_id)
            if point is None and isinstance(location_id, str) and location_id.endswith(":high"):
                point = self.location_points.get(location_id[:-5])
            if point is None:
                continue
            index = offsets.get(location_id, 0)
            offsets[location_id] = index + 1
            x = point.x() - 48 + (index % 5) * 20
            y = point.y() + 37 + (index // 5) * 20
            marker = QGraphicsEllipseItem(x, y, 14, 14)
            marker.setPen(QPen(QColor("#1d4ed8"), 1))
            marker.setBrush(QBrush(QColor("#60a5fa")))
            marker.setToolTip(f"{actor.name} ({actor.character_id})")
            self.addItem(marker)

