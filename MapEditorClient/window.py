"""Main window controller for the Qt map editor."""

from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGraphicsScene,
    QInputDialog,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
)

from MapEditorClient import APPLICATION_NAME
from MapEditorClient.graphics import LocationItem, RoadItem
from MapEditorClient.model import MapDocument, load_map_document, save_map_document
from MapEditorClient.ui_mapeditor import Ui_MainWindow

USER_ROLE = Qt.ItemDataRole.UserRole

# Keep Python-owned top-level windows alive until Qt has delivered their
# deferred deletion on the GUI thread. A Python cycle collector can otherwise
# finalize a closed window from an unrelated worker while Qt dispatches events.
_LIVE_WINDOWS = {}


class MapEditorWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        # close() otherwise only hides this window. Let Qt destroy its native
        # children on the GUI thread rather than a later Python GC thread.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.document: MapDocument | None = None
        self.current_path: Path | None = None
        self.dirty = False
        self._syncing_selection = False
        self.location_items: dict[str, LocationItem] = {}
        self.road_items: dict[str, RoadItem] = {}

        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(-1200, -900, 2400, 1800)
        self.ui.mapView.setScene(self.scene)
        self.ui.mapView.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.ui.mapView.setDragMode(self.ui.mapView.DragMode.RubberBandDrag)
        self.ui.mapView.setTransformationAnchor(self.ui.mapView.ViewportAnchor.AnchorUnderMouse)
        self.ui.objectList.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.ui.roadConnectionsList.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.ui.mainSplitter.setSizes([190, 560, 240])
        self.ui.menubar.hide()

        self._configure_actions()
        self._connect_signals()
        self._show_selection([])
        self._update_map_action_state()
        self._update_title()
        self.statusBar().showMessage("请先新建或打开一张地图。")
        if path is not None:
            self.open_path(path)
        key = id(self)
        _LIVE_WINDOWS[key] = self
        self.destroyed.connect(lambda _object=None, key=key: _LIVE_WINDOWS.pop(key, None))

    def _configure_actions(self):
        self.ui.actionNewMap.setShortcut(QKeySequence.StandardKey.New)
        self.ui.actionOpenMap.setShortcut(QKeySequence.StandardKey.Open)
        self.ui.actionSaveMap.setShortcut(QKeySequence.StandardKey.Save)
        self.ui.actionConnectRoad.setToolTip("连接两个或更多已选地点")

    def _connect_signals(self):
        self.ui.actionNewMap.triggered.connect(self.new_map)
        self.ui.actionOpenMap.triggered.connect(self.open_map)
        self.ui.actionSaveMap.triggered.connect(self.save_map)
        self.ui.actionAddLocation.triggered.connect(self.prompt_add_location)
        self.ui.actionConnectRoad.triggered.connect(self.connect_selected_locations)
        self.ui.actionDeleteSelected.triggered.connect(self.delete_selected)
        self.ui.objectList.itemSelectionChanged.connect(self._list_selection_changed)
        self.scene.selectionChanged.connect(self._scene_selection_changed)
        self.ui.nameEdit.editingFinished.connect(self._rename_selected_location)
        self.ui.buildingCheck.toggled.connect(self._building_changed)
        self.ui.highLevelCheck.toggled.connect(self._high_level_changed)
        self.ui.portCheck.toggled.connect(self._port_changed)

    def _set_dirty(self, value=True):
        if self.dirty == value:
            return
        self.dirty = value
        self._update_title()

    def _update_title(self):
        if self.document is None:
            filename = "未打开地图"
        else:
            filename = self.current_path.name if self.current_path else "未命名地图"
        marker = " *" if self.dirty else ""
        self.setWindowTitle(f"{filename}{marker} — {APPLICATION_NAME}")

    def _update_map_action_state(self):
        has_map = self.document is not None
        for action in (
            self.ui.actionAddLocation,
            self.ui.actionConnectRoad,
            self.ui.actionDeleteSelected,
        ):
            action.setVisible(has_map)
        self.ui.actionSaveMap.setEnabled(has_map)

    def _next_location_name(self):
        if self.document is None:
            return "地点1"
        index = 1
        names = {record.name for record in self.document.locations.values()}
        while f"地点{index}" in names:
            index += 1
        return f"地点{index}"

    def prompt_add_location(self):
        name, accepted = QInputDialog.getText(self, "新建地点", "地点名称：", text=self._next_location_name())
        if accepted:
            try:
                self.add_location(name)
            except ValueError as error:
                self._warning(str(error))

    def add_location(
        self,
        name,
        position=None,
        *,
        is_building=False,
        high_level=False,
        is_port=False,
    ):
        if self.document is None:
            # Public/API callers may construct a map directly; the toolbar
            # itself stays hidden until new_map/open_path establishes one.
            self.set_document(MapDocument())
        if position is None:
            center = self.ui.mapView.viewport().rect().center()
            position = self.ui.mapView.mapToScene(center)
            offset = len(self.document.locations) * 18
            position += QPointF(offset, offset)
        record = self.document.add_location(
            name,
            position.x(),
            position.y(),
            is_building=is_building,
            high_level=high_level,
            is_port=is_port,
        )
        self._add_location_item(record)
        self._rebuild_object_list([f"location:{record.location_id}"])
        self._set_dirty()
        self.statusBar().showMessage(f"已新建地点：{record.name}", 3000)
        return record

    def _add_location_item(self, record):
        item = LocationItem(record, self._location_moved)
        self.location_items[record.location_id] = item
        self.scene.addItem(item)
        return item

    def _add_road_item(self, road):
        item = RoadItem(road, [self.location_items[location_id] for location_id in road.location_ids])
        item.setToolTip(self.document.road_name(road))
        self.road_items[road.road_id] = item
        self.scene.addItem(item)
        return item

    def _location_moved(self, location_id, position):
        record = self.document.locations.get(location_id)
        if record is None:
            return
        record.x, record.y = position.x(), position.y()
        for road_id, road in self.document.roads.items():
            if location_id in road.location_ids:
                self.road_items[road_id].update_geometry()
        self._set_dirty()

    def connect_selected_locations(self):
        location_ids = []
        for key in self.selected_keys():
            kind, object_id = key.split(":", 1)
            if kind == "location" and object_id not in location_ids:
                location_ids.append(object_id)
        if len(location_ids) < 2:
            self._warning("请按住Ctrl选择至少两个地点，再连接道路。")
            return None
        try:
            return self.connect_location_ids(location_ids)
        except ValueError as error:
            self._warning(str(error))
            return None

    def connect_location_ids(self, location_ids):
        if self.document is None:
            raise ValueError("请先新建或打开地图")
        road = self.document.add_road(location_ids)
        self._add_road_item(road)
        key = f"road:{road.road_id}"
        self._rebuild_object_list([key])
        self._set_dirty()
        self.statusBar().showMessage(f"已连接道路：{self.document.road_name(road)}", 3000)
        return road

    def selected_keys(self):
        keys = []
        for item in self.scene.selectedItems():
            key = getattr(item, "key", None)
            if key and key not in keys:
                keys.append(key)
        for item in self.ui.objectList.selectedItems():
            key = item.data(USER_ROLE)
            if key and key not in keys:
                keys.append(key)
        return keys

    def _list_selection_changed(self):
        if self._syncing_selection:
            return
        keys = [item.data(USER_ROLE) for item in self.ui.objectList.selectedItems()]
        self._apply_selection(keys, update_list=False)

    def _scene_selection_changed(self):
        if self._syncing_selection:
            return
        keys = [item.key for item in self.scene.selectedItems() if hasattr(item, "key")]
        self._apply_selection(keys, update_scene=False)

    def _apply_selection(self, keys, *, update_list=True, update_scene=True):
        self._syncing_selection = True
        try:
            if update_scene:
                self.scene.clearSelection()
                for key in keys:
                    item = self._graphics_item(key)
                    if item is not None:
                        item.setSelected(True)
            if update_list:
                self.ui.objectList.clearSelection()
                for index in range(self.ui.objectList.count()):
                    item = self.ui.objectList.item(index)
                    if item.data(USER_ROLE) in keys:
                        item.setSelected(True)
        finally:
            self._syncing_selection = False
        self._show_selection(keys)

    def _graphics_item(self, key):
        kind, object_id = key.split(":", 1)
        return self.location_items.get(object_id) if kind == "location" else self.road_items.get(object_id)

    def _show_selection(self, keys):
        self.ui.locationPropertiesGroup.hide()
        self.ui.roadPropertiesGroup.hide()
        if self.document is None:
            self.ui.selectionLabel.setText("无地图")
            return
        if len(keys) != 1:
            self.ui.selectionLabel.setText("未选择地图对象" if not keys else f"已选择 {len(keys)} 个地图对象")
            return
        kind, object_id = keys[0].split(":", 1)
        if kind == "location" and object_id in self.document.locations:
            record = self.document.locations[object_id]
            self.ui.selectionLabel.setText(record.name)
            self._set_widget_value(self.ui.nameEdit, record.name)
            self._set_widget_value(self.ui.buildingCheck, record.is_building)
            self._set_widget_value(self.ui.highLevelCheck, record.high_level)
            self._set_widget_value(self.ui.portCheck, record.is_port)
            self.ui.locationPropertiesGroup.show()
        elif kind == "road" and object_id in self.document.roads:
            road = self.document.roads[object_id]
            self.ui.selectionLabel.setText(self.document.road_name(road))
            self.ui.roadConnectionsList.clear()
            self.ui.roadConnectionsList.addItems(
                [self.document.locations[location_id].name for location_id in road.location_ids]
            )
            self.ui.roadPropertiesGroup.show()

    @staticmethod
    def _set_widget_value(widget, value):
        previous = widget.blockSignals(True)
        try:
            if hasattr(widget, "setChecked") and isinstance(value, bool):
                widget.setChecked(value)
            else:
                widget.setText(value)
        finally:
            widget.blockSignals(previous)

    def _selected_location(self):
        if self.document is None:
            return None
        keys = self.selected_keys()
        if len(keys) != 1 or not keys[0].startswith("location:"):
            return None
        return self.document.locations.get(keys[0].split(":", 1)[1])

    def _rename_selected_location(self):
        record = self._selected_location()
        if record is None:
            return
        old_name = record.name
        try:
            self.document.rename_location(record.location_id, self.ui.nameEdit.text())
        except ValueError as error:
            self._set_widget_value(self.ui.nameEdit, old_name)
            self._warning(str(error))
            return
        self.location_items[record.location_id].update_record(record)
        for road_id, road in self.document.roads.items():
            if record.location_id in road.location_ids:
                self.road_items[road_id].setToolTip(self.document.road_name(road))
        self._rebuild_object_list([f"location:{record.location_id}"])
        self._set_dirty()

    def _building_changed(self, checked):
        record = self._selected_location()
        if record is None or record.is_building == checked:
            return
        record.is_building = checked
        if checked and record.is_port:
            record.is_port = False
            self._set_widget_value(self.ui.portCheck, False)
        self.location_items[record.location_id].update_record(record)
        self._set_dirty()

    def _high_level_changed(self, checked):
        record = self._selected_location()
        if record is None or record.high_level == checked:
            return
        record.high_level = checked
        if checked and record.is_port:
            record.is_port = False
            self._set_widget_value(self.ui.portCheck, False)
        self.location_items[record.location_id].update_record(record)
        self._set_dirty()

    def _port_changed(self, checked):
        record = self._selected_location()
        if record is None or record.is_port == checked:
            return
        record.is_port = checked
        if checked:
            record.is_building = False
            record.high_level = False
            self._set_widget_value(self.ui.buildingCheck, False)
            self._set_widget_value(self.ui.highLevelCheck, False)
        self.location_items[record.location_id].update_record(record)
        self._set_dirty()

    def delete_selected(self):
        keys = self.selected_keys()
        if not keys:
            return False
        answer = QMessageBox.question(
            self,
            "删除地图对象",
            f"确定删除选中的 {len(keys)} 个对象吗？删除地点也会删除相连道路。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.delete_keys(keys)
        return True

    def delete_keys(self, keys):
        if self.document is None:
            return False
        road_ids = {key.split(":", 1)[1] for key in keys if key.startswith("road:")}
        location_ids = {key.split(":", 1)[1] for key in keys if key.startswith("location:")}
        for road_id, road in list(self.document.roads.items()):
            if road_id in road_ids or any(location_id in road.location_ids for location_id in location_ids):
                road_ids.add(road_id)
        for road_id in road_ids:
            self.document.delete_road(road_id)
            item = self.road_items.pop(road_id, None)
            if item is not None:
                self.scene.removeItem(item)
        for location_id in location_ids:
            self.document.delete_location(location_id)
            item = self.location_items.pop(location_id, None)
            if item is not None:
                self.scene.removeItem(item)
        self._rebuild_object_list()
        self._show_selection([])
        self._set_dirty()

    def _rebuild_object_list(self, selected_keys=None):
        selected_keys = list(selected_keys or [])
        self._syncing_selection = True
        try:
            self.ui.objectList.clear()
            if self.document is None:
                return
            for record in self.document.locations.values():
                item = QListWidgetItem(f"地点｜{record.name}")
                item.setData(USER_ROLE, f"location:{record.location_id}")
                self.ui.objectList.addItem(item)
            for road in self.document.roads.values():
                item = QListWidgetItem(f"道路｜{self.document.road_name(road)}")
                item.setData(USER_ROLE, f"road:{road.road_id}")
                self.ui.objectList.addItem(item)
        finally:
            self._syncing_selection = False
        self._apply_selection(selected_keys)

    def _clear_scene(self):
        self.scene.clear()
        self.location_items.clear()
        self.road_items.clear()
        self.ui.objectList.clear()
        self._show_selection([])

    def set_document(self, document, *, path=None):
        self._clear_scene()
        self.document = document
        self.current_path = Path(path) if path is not None else None
        for record in document.locations.values():
            self._add_location_item(record)
        for road in document.roads.values():
            self._add_road_item(road)
        self._rebuild_object_list()
        self._set_dirty(False)
        self._update_map_action_state()
        self._update_title()
        if self.location_items:
            self.ui.mapView.fitInView(self.scene.itemsBoundingRect().adjusted(-80, -80, 80, 80), Qt.AspectRatioMode.KeepAspectRatio)

    def _maybe_discard_changes(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "未保存的地图",
            "当前地图有未保存的修改，是否放弃？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def new_map(self):
        if not self._maybe_discard_changes():
            return False
        self.set_document(MapDocument())
        self.statusBar().showMessage("已新建空白地图", 3000)
        return True

    @staticmethod
    def maps_directory():
        path = Path(__file__).resolve().parents[1] / "userdata" / "maps"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def open_map(self):
        if not self._maybe_discard_changes():
            return False
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开地图",
            str(self.maps_directory()),
            "Papermoon地图 (*.pmap)",
        )
        return self.open_path(path) if path else False

    def open_path(self, path):
        try:
            document = load_map_document(path)
        except (OSError, ValueError) as error:
            self._warning(str(error))
            return False
        self.set_document(document, path=path)
        self.statusBar().showMessage(f"已打开：{path}", 3000)
        return True

    def save_map(self):
        if self.document is None:
            return False
        path = self.current_path
        if path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "保存地图",
                str(self.maps_directory() / "新地图.pmap"),
                "Papermoon地图 (*.pmap)",
            )
            if not filename:
                return False
            path = Path(filename)
            if path.suffix.lower() != ".pmap":
                path = path.with_suffix(".pmap")
        try:
            save_map_document(self.document, path)
        except OSError as error:
            self._warning(str(error))
            return False
        self.current_path = Path(path)
        self._set_dirty(False)
        self._update_title()
        self.statusBar().showMessage(f"已保存：{path}", 3000)
        return True

    def _warning(self, message):
        QMessageBox.warning(self, "地图编辑器", message)

    def closeEvent(self, event: QCloseEvent):
        if self._maybe_discard_changes():
            event.accept()
        else:
            event.ignore()

