"""Main window for preparing and running a Papermoon game."""

from datetime import datetime
import ast
import json
from pathlib import Path
import random
import shlex
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QTableWidgetItem,
)

from core.catalog import CatalogProject, activate_catalog_bundle, validate_catalog_bundle
from game.character.card_data import CHARACTER_CARD_DATA
from game.character.card_factory import create_character_from_card
from game.character.masters import Master
from game.character.servants import Servant
from game.game.game_manager import GameManager
from game.game.game_session import GameSession
from game.game.command_spell import CommandSpellService
from MapEditorClient.model import load_map_document
from MapEditorClient.model import MapDocument

from GameMasterClient import APPLICATION_NAME
from GameMasterClient.dialogs import CharacterStatusDialog, GroupEditorDialog
from GameMasterClient.graphics import ReadOnlyMapScene
from GameMasterClient.ui_gamemaster import Ui_MainWindow


SAVE_FORMAT = "papermoon_save"
SAVE_VERSION = 1
CLASS_SLOTS = (
    ("Saber", "saberGroupLabel", "saberLocation"),
    ("Archer", "archerGroupLabel", "archerLocation"),
    ("Lancer", "lancerGroupLabel", "lancerLocation"),
    ("Rider", "riderGroupLabel", "riderLocation"),
    ("Caster", "casterGroupLabel", "casterLocation"),
    ("Assassin", "assassinGroupLabel", "assassinLocation"),
    ("Berserker", "berserkerGroupLabel", "berserkerLocation"),
    ("Extra", "extraGroupLabel", "extraLocation"),
)


class GameMasterWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.setWindowTitle(APPLICATION_NAME)
        # Designer pages have very different natural sizes.  Ignore the
        # largest hidden page while the compact main menu is visible; each
        # working page is explicitly resized when opened.
        self.ui.mainStack.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        for page in (self.ui.setupPage, self.ui.gamePage,
                     self.ui.placementPage, self.ui.groupMemberPage):
            page.setMinimumSize(0, 0)
        self.ui.mainStack.setCurrentWidget(self.ui.mainMenuPage)

        self.project = CatalogProject()
        self._catalog_context = self.project.activate()
        self._catalog_context.__enter__()
        self.active_catalog = self.project.effective()
        self.map_path = None
        self.map_document = None
        self.game_map = None
        self.runtime_locations = {}
        self.location_ids = {}
        self.characters = []
        self.custom_groups = []
        self.placement_groups = []
        self.next_character_number = 10
        self._dynamic_placement_rows = []
        self.game_manager = None
        self.session = None
        self.event_cursor = 0
        self.pending_decision = None
        self.replay_inputs = []
        self.initial_random_state = None
        self.initial_positions = {}
        self._closing = False

        self.placement_scene = ReadOnlyMapScene(parent=self)
        self.live_scene = ReadOnlyMapScene(parent=self)
        self.ui.placementMapView.setScene(self.placement_scene)
        self.ui.gameMapView.setScene(self.live_scene)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self._poll_session)

        self._configure_tables()
        self._connect_signals()
        self._reset_game_page()
        self._sync_grail_condition_bounds()
        self.ui.mapSummaryLabel.setText("无地图")

    def _configure_tables(self):
        table = self.ui.characterTable
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(("内部ID", "名称", "类型", "职介", "主从关系"))
        table.setSelectionBehavior(table.SelectionBehavior.SelectRows)
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        groups = self.ui.customGroupTable
        groups.setColumnCount(2)
        groups.setHorizontalHeaderLabels(("分组名称", "成员"))
        groups.setSelectionBehavior(groups.SelectionBehavior.SelectRows)
        groups.setEditTriggers(groups.EditTrigger.NoEditTriggers)
        groups.horizontalHeader().setStretchLastSection(True)

    def _connect_signals(self):
        ui = self.ui
        ui.newGameButton.clicked.connect(self.open_setup)
        ui.loadGameButton.clicked.connect(self.load_game)
        ui.exitButton.clicked.connect(self.close)
        ui.backToMenuButton.clicked.connect(self.show_main_menu)
        ui.importMapButton.clicked.connect(self.import_map)
        ui.browseMapButton.clicked.connect(self.browse_map)
        ui.clearMapButton.clicked.connect(self.clear_map)
        ui.importCharacterButton.clicked.connect(self.import_character)
        ui.viewCharacterButton.clicked.connect(self.view_selected_character)
        ui.removeCharacterButton.clicked.connect(self.remove_selected_character)
        ui.setRelationshipButton.clicked.connect(self.set_relationship)
        ui.gameStartButton.clicked.connect(self.prepare_placement)
        ui.placementBackButton.clicked.connect(lambda: ui.mainStack.setCurrentWidget(ui.setupPage))
        ui.groupEditButton.clicked.connect(lambda: ui.mainStack.setCurrentWidget(ui.groupMemberPage))
        ui.newGroupButton.clicked.connect(self.new_custom_group)
        ui.removeGroupButton.clicked.connect(self.remove_custom_group)
        ui.confirmGroupButton.clicked.connect(self.confirm_groups)
        ui.resetGroupButton.clicked.connect(self.reset_groups)
        ui.addPlacementGroupButton.clicked.connect(self.new_custom_group)
        ui.removePlacementGroupButton.clicked.connect(self.remove_placement_group)
        ui.resetChooseButton.clicked.connect(self.reset_placements)
        ui.characterConfirmButton.clicked.connect(self.start_game)
        ui.nextTurnButton.clicked.connect(self.next_turn)
        ui.endGameButton.clicked.connect(self.end_game)
        ui.decisionConfirmButton.clicked.connect(self.submit_decision)
        ui.decisionBackButton.clicked.connect(self.cancel_decision_selection)
        ui.saveGameButton.clicked.connect(self.save_game)
        ui.commandExecutionButton.clicked.connect(self.execute_gm_command)
        ui.GMCommandEdit.returnPressed.connect(self.execute_gm_command)
        ui.grailAppearanceConditionSpinBox.valueChanged.connect(
            self._sync_grail_condition_bounds
        )
        ui.grailReadyConditionSpinBox.valueChanged.connect(
            self._sync_grail_condition_bounds
        )

    def _sync_grail_condition_bounds(self, _value=None):
        """Keep appearance <= ready without waiting for final submission."""
        appearance = self.ui.grailAppearanceConditionSpinBox
        ready = self.ui.grailReadyConditionSpinBox
        appearance.setMaximum(ready.value())
        ready.setMinimum(appearance.value())
        appearance.setToolTip("圣杯出现条件不能大于圣杯就绪条件")
        ready.setToolTip("创建游戏时，该值不能大于本局从者总数")

    def open_setup(self):
        if self.session is not None and self.session.state not in self.session.TERMINAL_STATES:
            QMessageBox.warning(self, "游戏正在运行", "请先结束当前游戏。")
            return
        self.ui.mainStack.setCurrentWidget(self.ui.setupPage)
        self._show_work_window()

    def show_main_menu(self):
        self.ui.mainStack.setCurrentWidget(self.ui.mainMenuPage)
        self.setMinimumSize(0, 0)
        self.resize(640, 480)
        self._center_on_screen()

    def _show_work_window(self):
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(1280, available.width() - 80), min(800, available.height() - 80))
        self._center_on_screen()

    def _center_on_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def browse_map(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入地图", "", "Papermoon地图 (*.pmap);;所有文件 (*)")
        if not path:
            return False
        self.ui.mapPathEdit.setText(path)
        self.ui.mapSummaryLabel.setText("已选择，等待导入")
        return True

    def import_map(self):
        path = self.ui.mapPathEdit.text().strip()
        if not path:
            if not self.browse_map():
                return
            path = self.ui.mapPathEdit.text().strip()
        try:
            document = load_map_document(path)
        except (OSError, ValueError) as error:
            self._error(error)
            return
        self.map_path = Path(path)
        self.map_document = document
        self.ui.mapPathEdit.setText(str(self.map_path))
        self.ui.mapSummaryLabel.setText(f"{len(document.locations)}个地点，{len(document.roads)}条道路")
        self.ui.grailLocationCombo.clear()
        for key, record in document.locations.items():
            self.ui.grailLocationCombo.addItem(record.name, key)
        self.placement_scene.set_document(document)
        self.live_scene.set_document(document)

    def clear_map(self):
        self.map_path = None
        self.map_document = None
        self.ui.mapPathEdit.clear()
        self.ui.mapSummaryLabel.setText("无地图")
        self.ui.grailLocationCombo.clear()
        self.placement_scene.clear()
        self.live_scene.clear()

    def import_character(self):
        cards = sorted(CHARACTER_CARD_DATA.items(), key=lambda pair: (pair[1]["character_type"], pair[1]["name"]))
        if not cards:
            self._error("当前角色库中没有可导入的角色卡")
            return
        labels = [f"{data['name']}  [{card_id}]" for card_id, data in cards]
        label, accepted = QInputDialog.getItem(self, "导入角色", "从已编辑的角色库选择：", labels, 0, False)
        if not accepted:
            return
        card_id = cards[labels.index(label)][0]
        default_name = CHARACTER_CARD_DATA[card_id]["name"]
        name, accepted = QInputDialog.getText(self, "角色名称", "本局显示名称：", text=default_name)
        if not accepted:
            return
        try:
            actor = create_character_from_card(card_id, name=name.strip() or default_name)
            actor._character_id = f"character{self.next_character_number}"
            self.next_character_number += 1
            self.characters.append(actor)
            self._refresh_character_table()
        except ValueError as error:
            self._error(error)

    def _selected_character(self):
        row = self.ui.characterTable.currentRow()
        if row < 0:
            raise ValueError("请先选择角色")
        character_id = self.ui.characterTable.item(row, 0).text()
        return next(actor for actor in self.characters if actor.character_id == character_id)

    def view_selected_character(self):
        try:
            CharacterStatusDialog(self._selected_character(), self).exec()
        except ValueError as error:
            self._error(error)

    def remove_selected_character(self):
        try:
            actor = self._selected_character()
        except ValueError as error:
            self._error(error)
            return
        if isinstance(actor, Master):
            for servant in list(actor.servants):
                actor.remove_servant(servant, trigger_master_lost=False)
        elif isinstance(actor, Servant) and actor.master is not None:
            actor.master.remove_servant(actor, trigger_master_lost=False)
        self.characters.remove(actor)
        self.custom_groups = [
            {**group, "member_ids": [item for item in group["member_ids"] if item != actor.character_id]}
            for group in self.custom_groups
            if any(item != actor.character_id for item in group["member_ids"])
        ]
        self._refresh_character_table()
        self._refresh_group_table()

    def set_relationship(self):
        masters = [actor for actor in self.characters if isinstance(actor, Master)]
        servants = [actor for actor in self.characters if isinstance(actor, Servant)]
        if not masters or not servants:
            self._error("至少需要一名御主和一名从者")
            return
        master_labels = [f"{actor.name} [{actor.character_id}]" for actor in masters]
        servant_labels = [f"{actor.name} [{actor.character_id}]" for actor in servants]
        master_label, ok = QInputDialog.getItem(self, "设置主从", "御主：", master_labels, 0, False)
        if not ok:
            return
        servant_label, ok = QInputDialog.getItem(self, "设置主从", "从者：", servant_labels, 0, False)
        if not ok:
            return
        master = masters[master_labels.index(master_label)]
        servant = servants[servant_labels.index(servant_label)]
        if not master.add_servant(servant):
            self._error("该御主的从者数量已达上限")
            return
        self._refresh_character_table()

    def _refresh_character_table(self):
        table = self.ui.characterTable
        table.setRowCount(len(self.characters))
        for row, actor in enumerate(self.characters):
            relation = ""
            if isinstance(actor, Master) and actor.servants:
                relation = "从者：" + "、".join(item.name for item in actor.servants)
            elif isinstance(actor, Servant) and actor.master is not None:
                relation = f"御主：{actor.master.name}"
            values = (actor.character_id, actor.name, actor.entity_type,
                      getattr(actor, "servant_class", ""), relation)
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def prepare_placement(self):
        try:
            maximum = self.ui.MaximumTurnsSpinBox.value()
            appearance = self.ui.grailAppearanceConditionSpinBox.value()
            ready = self.ui.grailReadyConditionSpinBox.value()
            if appearance > ready:
                raise ValueError("圣杯出现条件不能大于圣杯就绪条件")
            if self.map_document is None:
                raise ValueError("请先导入地图")
            if not self.characters:
                raise ValueError("请先导入至少一名参战角色")
            servant_count = sum(isinstance(actor, Servant) for actor in self.characters)
            if ready > servant_count:
                raise ValueError(
                    f"圣杯就绪条件为{ready}，但本局开始时只有{servant_count}名从者"
                )
            if self.ui.grailLocationCombo.currentData() is None:
                raise ValueError("请选择圣杯出现地点")
        except ValueError as error:
            self._error(error)
            return
        self.rules = {"maximum_turns": maximum, "grail_appearance_deaths": appearance,
                      "grail_ready_deaths": ready,
                      "grail_location_id": self.ui.grailLocationCombo.currentData()}
        self._build_runtime_map()
        self._build_placement_groups()
        self.ui.mainStack.setCurrentWidget(self.ui.placementPage)
        self._show_work_window()
        self._refresh_placement_progress()
        self.ui.placementMapView.fitInView(self.placement_scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def _build_runtime_map(self):
        self.game_map = self.map_document.to_game_map()
        self.runtime_locations = {}
        self.location_ids = {}
        for key, record in self.map_document.locations.items():
            location = self.game_map.locations[record.name]
            self.runtime_locations[key] = location
            self.location_ids[location] = key
            if location.high_level_location is not None:
                self.runtime_locations[f"{key}:high"] = location.high_level_location
                self.location_ids[location.high_level_location] = f"{key}:high"

    def _build_placement_groups(self):
        self._clear_dynamic_placement_rows()
        groups = []
        used = set()
        by_class = {name: [] for name, _, _ in CLASS_SLOTS}
        for servant in (actor for actor in self.characters if isinstance(actor, Servant)):
            key = servant.servant_class if servant.servant_class in by_class else "Extra"
            members = [servant]
            if servant.master is not None:
                members.insert(0, servant.master)
            by_class[key].append(members)
        custom_ids = {item for group in self.custom_groups for item in group["member_ids"]}
        for class_name, label_name, combo_name in CLASS_SLOTS:
            label, combo = getattr(self.ui, label_name), getattr(self.ui, combo_name)
            entries = by_class[class_name]
            members = entries.pop(0) if entries else []
            members = [actor for actor in members
                       if actor.character_id not in custom_ids and actor.character_id not in used]
            label.setText(class_name + ("组：" + "、".join(actor.name for actor in members) if members else "组（无）"))
            label.setVisible(bool(members))
            combo.setVisible(bool(members))
            self._fill_location_combo(combo)
            if members:
                group = {"name": f"{class_name}组", "members": members, "combo": combo}
                groups.append(group)
                used.update(actor.character_id for actor in members)
            for duplicate in entries:
                duplicate = [actor for actor in duplicate
                             if actor.character_id not in custom_ids and actor.character_id not in used]
                if duplicate:
                    group = self._dynamic_placement_group(f"{class_name}追加组", duplicate)
                    groups.append(group)
                    used.update(actor.character_id for actor in duplicate)
        for definition in self.custom_groups:
            members = [actor for actor in self.characters
                       if actor.character_id in definition["member_ids"] and actor.character_id not in used]
            if members:
                groups.append(self._dynamic_placement_group(definition["name"], members))
                used.update(actor.character_id for actor in members)
        for actor in self.characters:
            if actor.character_id not in used:
                groups.append(self._dynamic_placement_group(actor.name, [actor]))
        self.placement_groups = groups
        self._refresh_placement_list()

    def _clear_dynamic_placement_rows(self):
        for layout, label, combo in self._dynamic_placement_rows:
            self.ui.placementRowsLayout.removeItem(layout)
            label.deleteLater()
            combo.deleteLater()
            layout.deleteLater()
        self._dynamic_placement_rows.clear()

    def _dynamic_placement_group(self, name, members):
        layout = QHBoxLayout()
        label = QLabel(name, self.ui.scrollAreaWidgetContents_2)
        combo = QComboBox(self.ui.scrollAreaWidgetContents_2)
        layout.addWidget(label)
        layout.addWidget(combo)
        self.ui.placementRowsLayout.addLayout(layout)
        self._fill_location_combo(combo)
        self._dynamic_placement_rows.append((layout, label, combo))
        return {"name": name, "members": members, "combo": combo}

    def _fill_location_combo(self, combo):
        combo.clear()
        combo.addItem("请选择地点", None)
        for key, location in self.runtime_locations.items():
            combo.addItem(location.name, key)
        combo.currentIndexChanged.connect(self._refresh_placement_progress)

    def _refresh_placement_list(self):
        self.ui.placementCharacterList.clear()
        for group in self.placement_groups:
            location = group["combo"].currentText() if group["combo"] and group["combo"].currentData() else "未设置"
            self.ui.placementCharacterList.addItem(
                f"{group['name']}：{'、'.join(actor.name for actor in group['members'])} → {location}"
            )

    def _refresh_placement_progress(self):
        assigned = sum(len(group["members"]) for group in self.placement_groups
                       if group["combo"] is not None and group["combo"].currentData() is not None)
        total = len(self.characters)
        self.ui.placementProgressLabel.setText(f"已设置{assigned}/{total}")
        self._refresh_placement_list()

    def new_custom_group(self):
        dialog = GroupEditorDialog(self.characters, parent=self)
        if not dialog.exec():
            return
        try:
            group = dialog.value()
            existing = {item for current in self.custom_groups for item in current["member_ids"]}
            if existing.intersection(group["member_ids"]):
                raise ValueError("一个角色不能同时属于两个自定义初始位置组")
            self.custom_groups.append(group)
            self._refresh_group_table()
            if self.ui.mainStack.currentWidget() is self.ui.placementPage:
                self._build_placement_groups()
        except ValueError as error:
            self._error(error)

    def remove_custom_group(self):
        row = self.ui.customGroupTable.currentRow()
        if row < 0:
            self._error("请先选择要删除的分组")
            return
        self.custom_groups.pop(row)
        self._refresh_group_table()
        if self.ui.mainStack.currentWidget() is self.ui.placementPage:
            self._build_placement_groups()

    def remove_placement_group(self):
        row = self.ui.placementCharacterList.currentRow()
        if row < 0 or row >= len(self.placement_groups):
            self._error("请先在左侧选择要删除的自定义分组")
            return
        group = self.placement_groups[row]
        member_ids = {actor.character_id for actor in group["members"]}
        index = next((index for index, definition in enumerate(self.custom_groups)
                      if definition["name"] == group["name"]
                      and set(definition["member_ids"]) == member_ids), None)
        if index is None:
            self._error("默认主从组和单独角色组不能在这里删除")
            return
        self.custom_groups.pop(index)
        self._refresh_group_table()
        self._build_placement_groups()

    def _refresh_group_table(self):
        table = self.ui.customGroupTable
        table.setRowCount(len(self.custom_groups))
        lookup = {actor.character_id: actor.name for actor in self.characters}
        for row, group in enumerate(self.custom_groups):
            table.setItem(row, 0, QTableWidgetItem(group["name"]))
            table.setItem(row, 1, QTableWidgetItem("、".join(lookup.get(item, item) for item in group["member_ids"])))

    def confirm_groups(self):
        self._build_placement_groups()
        self.ui.mainStack.setCurrentWidget(self.ui.placementPage)

    def reset_groups(self):
        self.custom_groups.clear()
        self._refresh_group_table()

    def reset_placements(self):
        for group in self.placement_groups:
            if group["combo"] is not None:
                group["combo"].setCurrentIndex(0)
        self._refresh_placement_progress()

    def start_game(self):
        if any(group["combo"].currentData() is None for group in self.placement_groups):
            self._error("仍有角色组没有设置初始位置")
            return
        answer = QMessageBox.question(self, "开始游戏", "请确保所有角色和地图已经正确导入。\n确定开始后将不能变更参战角色和地图。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        for group in self.placement_groups:
            key = group["combo"].currentData()
            position = self.runtime_locations[key]
            for actor in group["members"]:
                actor.position = position
        self.initial_positions = {
            actor.character_id: self.location_ids.get(actor.position)
            for actor in self.characters
        }
        self.initial_random_state = random.getstate()
        self.replay_inputs = []
        grail = self.runtime_locations[self.rules["grail_location_id"]]
        self.game_manager = GameManager(
            self.characters, grail,
            maximum_turns=self.rules["maximum_turns"],
            grail_appearance_deaths=self.rules["grail_appearance_deaths"],
            grail_ready_deaths=self.rules["grail_ready_deaths"],
            character_id_allocator=self._allocate_character_id,
        )
        self.game_manager.game_map = self.game_map
        controllers = {actor.character_id: "gm" for actor in self.characters}
        self.session = GameSession(self.game_manager, controllers, gm_id="gm", manual_turns=True)
        self.event_cursor = 0
        self.pending_decision = None
        self.ui.mainStack.setCurrentWidget(self.ui.gamePage)
        self._show_work_window()
        self._rebuild_character_buttons()
        self._append_log("游戏已建立，等待GM启动第一回合。")
        self.ui.nextTurnButton.setEnabled(False)
        self.ui.saveGameButton.setEnabled(False)
        self.session.start()
        self.poll_timer.start()

    def _rebuild_character_buttons(self):
        layout = self.ui.gameCharacterButtonLayout
        for index in reversed(range(layout.count())):
            widget = layout.itemAt(index).widget()
            if widget is not None:
                widget.deleteLater()
        for actor in self.characters:
            button = QPushButton(actor.name)
            button.setToolTip(actor.character_id)
            button.clicked.connect(lambda _checked=False, item=actor: self._open_character_status(item))
            layout.addWidget(button)
        layout.addStretch(1)

    def _open_character_status(self, actor):
        request = self.pending_decision
        CharacterStatusDialog(
            actor,
            self,
            command_spell_callback=self.open_command_spell,
            decision_request=request,
            decision_callback=(lambda option_id: self._submit_option_id(request, option_id)),
        ).exec()

    def _submit_option_id(self, request, option_id):
        if request is None or request is not self.pending_decision:
            self._error("该行动选择已经过期")
            return
        try:
            index = next(index for index, option in enumerate(request["options"])
                         if option["option_id"] == option_id)
            self.session.submit_decision(
                "gm", request["request_id"], request["revision"], option_id=option_id,
            )
            self.replay_inputs.append({"type": "decision", "kind": "choice", "option_index": index})
            self.ui.decisionConfirmButton.setEnabled(False)
        except (StopIteration, ValueError, PermissionError) as error:
            self._error("未知或已经过期的行动选项" if isinstance(error, StopIteration) else error)

    def _poll_session(self):
        if self.session is None:
            return
        try:
            events = self.session.get_events("gm", after=self.event_cursor, timeout=0)
        except (ValueError, PermissionError) as error:
            self._append_log(f"会话读取失败：{error}")
            return
        for event in events:
            self.event_cursor = event["sequence"]
            self._handle_event(event)
        self._refresh_live_view()

    def _handle_event(self, event):
        kind, payload = event["type"], event["payload"]
        if kind == "safe_checkpoint":
            turn = payload["turn"]
            self.ui.checkpointStatusLabel.setText(f"第{turn}回合结束后的安全节点")
            self.ui.nextTurnButton.setEnabled(True)
            self.ui.saveGameButton.setEnabled(True)
            self.ui.gamePhaseLabel.setText("等待推进")
            self._append_log(f"抵达安全节点（已完成{turn}个全局回合）。")
        elif kind == "decision_requested":
            self.pending_decision = payload
            self._show_decision(payload)
            self._append_log(f"等待决定：{payload['phase']} {payload['prompt']}")
        elif kind == "decision_answered":
            self.pending_decision = None
            self._clear_decision("决定已提交，正在结算……")
        elif kind == "decision_invalidated":
            self.pending_decision = None
            self._clear_decision("行动改变，正在刷新可选项……")
        elif kind == "rule_report":
            actor = payload.get("actor") or "系统"
            report_type = payload.get("report_type", payload.get("type", "规则事件"))
            self._append_log(f"{actor}：{report_type}")
        elif kind == "notification":
            self._append_log(payload.get("message", ""))
        elif kind == "operation_failed":
            self._error(payload.get("error", "操作失败"))
        elif kind == "global_turn_completed":
            self._append_log(f"第{payload['turn']}回合结算完成。")
        elif kind == "session_ended":
            self._clear_decision("游戏已结束")
            self.ui.nextTurnButton.setEnabled(False)
            self.ui.saveGameButton.setEnabled(False)
            self.ui.checkpointStatusLabel.setText(f"游戏结束：{payload.get('reason')}")
            self._append_log(f"游戏结束：{payload.get('reason')}")
            self.poll_timer.stop()

    def _show_decision(self, request):
        self.ui.currentRequestLabel.setText(f"{request['phase']} · {request['character_id']}")
        self.ui.decisionPromptLabel.setText(request["prompt"] or "请选择本阶段行动")
        self.ui.currentActorLabel.setText(f"当前角色：{self._actor_name(request['character_id'])}")
        self.ui.gamePhaseLabel.setText(request["phase"])
        self.ui.decisionConfirmButton.setEnabled(True)
        self.ui.decisionBackButton.setEnabled(bool(request.get("allow_cancel")))
        if request["kind"] == "numeric":
            self.ui.decisionInputStack.setCurrentWidget(self.ui.numberDecisionPage)
            self.ui.spinBox.setRange(request["minimum"], request["maximum"])
            self.ui.spinBox.setValue(request["minimum"])
            self.ui.numberDecisionLabel.setText(f"请输入 {request['minimum']} 至 {request['maximum']}：")
        else:
            self.ui.decisionInputStack.setCurrentWidget(self.ui.choiceDecisionPage)
            self.ui.decisionOptionList.clear()
            for option in request["options"]:
                self.ui.decisionOptionList.addItem(option["label"])
                self.ui.decisionOptionList.item(self.ui.decisionOptionList.count() - 1).setData(
                    Qt.ItemDataRole.UserRole, option["option_id"]
                )
            if self.ui.decisionOptionList.count():
                self.ui.decisionOptionList.setCurrentRow(0)

    def submit_decision(self):
        request = self.pending_decision
        if request is None:
            return
        try:
            arguments = {"value": self.ui.spinBox.value()} if request["kind"] == "numeric" else {}
            if request["kind"] == "choice":
                item = self.ui.decisionOptionList.currentItem()
                if item is None:
                    raise ValueError("请选择一个选项")
                arguments["option_id"] = item.data(Qt.ItemDataRole.UserRole)
            self.session.submit_decision("gm", request["request_id"], request["revision"], **arguments)
            record = {"type": "decision", "kind": request["kind"]}
            if request["kind"] == "numeric":
                record["value"] = arguments["value"]
            else:
                record["option_index"] = self.ui.decisionOptionList.currentRow()
            self.replay_inputs.append(record)
            self.ui.decisionConfirmButton.setEnabled(False)
        except (ValueError, PermissionError) as error:
            self._error(error)

    def cancel_decision_selection(self):
        self.ui.decisionOptionList.clearSelection()

    def next_turn(self):
        try:
            self.session.request_next_turn("gm")
            self.replay_inputs.append({"type": "next_turn"})
            self.ui.nextTurnButton.setEnabled(False)
            self.ui.saveGameButton.setEnabled(False)
            self.ui.checkpointStatusLabel.setText("本回合正在运行")
        except (ValueError, PermissionError) as error:
            self._error(error)

    def end_game(self):
        if self.session is None:
            return
        if QMessageBox.question(self, "结束游戏", "确定结束当前游戏吗？") != QMessageBox.StandardButton.Yes:
            return
        self.session.stop()

    def execute_gm_command(self):
        text = self.ui.GMCommandEdit.text().strip()
        if not text or self.session is None:
            return
        try:
            parts = shlex.split(text)
            command = parts[0].lower()
            if command == "kill" and len(parts) == 2:
                target_id = self._actor_id(parts[1])
                parameters = {}
                operation = self.session.gm_command("gm", "kill", target_id=target_id)
            elif command == "add_resource" and len(parts) == 4:
                target_id = self._actor_id(parts[1])
                parameters = {"resource": parts[2], "amount": int(parts[3])}
                operation = self.session.gm_command("gm", command, target_id=target_id, **parameters)
            elif command == "damage" and len(parts) == 4:
                target_id = self._actor_id(parts[1])
                parameters = {"damage_type": int(parts[2]), "amount": int(parts[3])}
                operation = self.session.gm_command("gm", command, target_id=target_id, **parameters)
            elif command == "teleport" and len(parts) == 3:
                target_id = self._actor_id(parts[1])
                parameters = {"destination_id": self._position_id(parts[2])}
                operation = self.session.gm_command("gm", command, target_id=target_id, **parameters)
            else:
                raise ValueError("命令格式错误；可用：add_resource、damage、teleport、kill")
            self.ui.GMCommandEdit.clear()
            replay_parameters = dict(parameters)
            if command == "teleport":
                snapshot = self.session.get_snapshot("gm")
                replay_parameters = {
                    "destination_name": next(
                        item["name"] for item in snapshot["positions"]
                        if item["position_id"] == parameters["destination_id"]
                    )
                }
            self.replay_inputs.append({"type": "gm_command", "command": command,
                                       "target_id": target_id, "parameters": replay_parameters})
            self._append_log(f"已提交GM命令（{operation}）。")
        except (ValueError, PermissionError) as error:
            self._error(error)

    def open_command_spell(self, master):
        if self.session is None or self.pending_decision is None:
            self._error("令咒需要在一个正在等待决定的行动窗口中使用")
            return
        service = CommandSpellService(self.game_manager)
        effects = [("获得临时MP（1划）", "mp"), ("下一次伤害+90（1划）", "damage")]
        if master.command_spell >= 2 and any(service.teleport_destinations(master, servant)
                                             for servant in master.servants):
            effects.append(("瞬间移动从者（2划）", "teleport"))
        label, ok = QInputDialog.getItem(self, "使用令咒", "选择效果：", [item[0] for item in effects], 0, False)
        if not ok:
            return
        effect = dict(effects)[label]
        targets = (master.servants if effect == "teleport" else service.controlled_characters(master))
        targets = [target for target in targets if target.is_alive()]
        target_labels = [f"{target.name} [{target.character_id}]" for target in targets]
        target_label, ok = QInputDialog.getItem(self, "使用令咒", "作用角色：", target_labels, 0, False)
        if not ok:
            return
        target = targets[target_labels.index(target_label)]
        arguments = {"master_id": master.character_id, "target_id": target.character_id, "effect": effect}
        replay = {"type": "command_spell", "master_id": master.character_id,
                  "target_id": target.character_id, "effect": effect}
        if effect == "teleport":
            destinations = service.teleport_destinations(master, target)
            if not destinations:
                self._error("该从者目前没有可用的已抵达地点")
                return
            names = [position.name for position in destinations]
            destination_name, ok = QInputDialog.getItem(self, "令咒瞬移", "目的地：", names, 0, False)
            if not ok:
                return
            destination = destinations[names.index(destination_name)]
            snapshot = self.session.get_snapshot("gm")
            matches = [item for item in snapshot["positions"] if item["name"] == destination.name]
            if len(matches) != 1:
                self._error("无法唯一确定令咒目的地")
                return
            arguments["destination_id"] = matches[0]["position_id"]
            replay["destination_name"] = destination.name
        try:
            self.session.command_spell("gm", **arguments)
            self.replay_inputs.append(replay)
        except (ValueError, PermissionError) as error:
            self._error(error)

    def save_game(self):
        if self.session is None or self.session.state != "ready":
            self._error("只能在完整回合结束后的安全节点保存")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择存档文件夹")
        if not directory:
            return
        name = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        path = Path(directory) / f"{name}.psav"
        suffix = 1
        while path.exists():
            path = Path(directory) / f"{name}_{suffix}.psav"
            suffix += 1
        payload = self._save_payload()
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        self._append_log(f"已保存：{path}")
        QMessageBox.information(self, "保存完成", str(path))

    def _save_payload(self):
        snapshot = self.session.get_snapshot("gm")
        return {
            "format": SAVE_FORMAT,
            "format_version": SAVE_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "resumable": True,
            "random_state": repr(self.initial_random_state),
            "inputs": list(self.replay_inputs),
            "map": self.map_document.to_dict(),
            "rules": self.rules,
            "catalog": self.active_catalog,
            "characters": [{
                "character_id": actor.character_id,
                "card_id": getattr(actor, "card_id", None),
                "name": actor.name,
                "initial_position": self.initial_positions.get(actor.character_id),
                "master_id": getattr(getattr(actor, "master", None), "character_id", None),
            } for actor in self.characters],
            "snapshot": snapshot,
        }

    def load_game(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载游戏", "", "Papermoon存档 (*.psav);;所有文件 (*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if data.get("format") != SAVE_FORMAT or data.get("format_version") != SAVE_VERSION:
                raise ValueError("不是受支持的Papermoon存档")
            if not data.get("resumable", False):
                raise ValueError("该存档只包含只读快照，不能恢复继续运行")
            self._restore_save(data)
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError,
                IndexError, SyntaxError) as error:
            if self.session is not None and self.session.state not in self.session.TERMINAL_STATES:
                self.session.stop()
                self.session.join(2)
            self._error(error)

    def _restore_save(self, data):
        if self.session is not None and self.session.state not in self.session.TERMINAL_STATES:
            raise ValueError("请先结束当前游戏")
        expected_catalog = data.get("catalog", {})
        if expected_catalog and expected_catalog != self.active_catalog:
            embedded = validate_catalog_bundle(expected_catalog)
            self._catalog_context.__exit__(None, None, None)
            self._catalog_context = activate_catalog_bundle(embedded)
            self._catalog_context.__enter__()
            self.active_catalog = embedded
        self.map_document = MapDocument.from_dict(data["map"])
        self.map_path = None
        self.rules = dict(data["rules"])
        self.characters = []
        records = data["characters"]
        for record in records:
            actor = create_character_from_card(record["card_id"], name=record["name"])
            actor._character_id = record["character_id"]
            self.characters.append(actor)
        self.next_character_number = max(
            [int(actor.character_id.removeprefix("character")) + 1
             for actor in self.characters if actor.character_id.removeprefix("character").isdigit()]
            or [10]
        )
        by_id = {actor.character_id: actor for actor in self.characters}
        for record in records:
            master_id = record.get("master_id")
            if master_id is not None:
                master = by_id.get(master_id)
                servant = by_id[record["character_id"]]
                if not isinstance(master, Master) or not isinstance(servant, Servant) or not master.add_servant(servant):
                    raise ValueError("存档中的主从关系无效")
        self._build_runtime_map()
        self.initial_positions = {}
        for record in records:
            key = record.get("initial_position")
            if key not in self.runtime_locations:
                raise ValueError("存档引用了不存在的初始地点")
            by_id[record["character_id"]].position = self.runtime_locations[key]
            self.initial_positions[record["character_id"]] = key
        grail = self.runtime_locations[self.rules["grail_location_id"]]
        self.game_manager = GameManager(
            self.characters, grail,
            maximum_turns=self.rules["maximum_turns"],
            grail_appearance_deaths=self.rules["grail_appearance_deaths"],
            grail_ready_deaths=self.rules["grail_ready_deaths"],
            character_id_allocator=self._allocate_character_id,
        )
        self.game_manager.game_map = self.game_map
        self.initial_random_state = ast.literal_eval(data["random_state"])
        random.setstate(self.initial_random_state)
        controllers = {actor.character_id: "gm" for actor in self.characters}
        self.session = GameSession(self.game_manager, controllers, gm_id="gm", manual_turns=True)
        self.event_cursor = 0
        self.pending_decision = None
        self.session.start()
        self._replay_saved_inputs(data.get("inputs", []))
        expected_turn = data.get("snapshot", {}).get("turn")
        if self.game_manager.turn_manager.turn != expected_turn or self.session.state != "ready":
            self.session.stop()
            raise ValueError("存档重放没有抵达预期安全节点")
        self.replay_inputs = list(data.get("inputs", []))
        self.placement_scene.set_document(self.map_document)
        self.live_scene.set_document(self.map_document)
        self.ui.mainStack.setCurrentWidget(self.ui.gamePage)
        self._show_work_window()
        self._rebuild_character_buttons()
        self._refresh_character_table()
        self._append_log(f"已加载存档，恢复到第{expected_turn}回合结束后的安全节点。")
        self.poll_timer.start()

    def _replay_saved_inputs(self, inputs):
        deadline = time.monotonic() + max(15, len(inputs) * 2)
        for entry in inputs:
            while time.monotonic() < deadline:
                QApplication.processEvents()
                state = self.session.state
                request = self.session.get_pending_decision("gm")
                if entry["type"] == "next_turn" and state == "ready":
                    self.session.request_next_turn("gm")
                    break
                if entry["type"] == "decision" and request is not None:
                    if entry["kind"] != request["kind"]:
                        raise ValueError("存档决策类型与当前规则不一致")
                    arguments = ({"value": entry["value"]} if request["kind"] == "numeric" else
                                 {"option_id": request["options"][entry["option_index"]]["option_id"]})
                    self.session.submit_decision("gm", request["request_id"], request["revision"], **arguments)
                    break
                if entry["type"] == "gm_command" and (state == "ready" or request is not None):
                    parameters = dict(entry.get("parameters", {}))
                    if entry["command"] == "teleport":
                        destination_name = parameters.pop("destination_name")
                        snapshot = self.session.get_snapshot("gm")
                        matches = [item for item in snapshot["positions"] if item["name"] == destination_name]
                        if len(matches) != 1:
                            raise ValueError("存档中的GM传送目的地无法唯一匹配")
                        parameters["destination_id"] = matches[0]["position_id"]
                    self.session.gm_command("gm", entry["command"], target_id=entry["target_id"],
                                            **parameters)
                    break
                if entry["type"] == "command_spell" and request is not None:
                    arguments = {key: entry[key] for key in ("master_id", "target_id", "effect")}
                    if entry["effect"] == "teleport":
                        snapshot = self.session.get_snapshot("gm")
                        matches = [item for item in snapshot["positions"]
                                   if item["name"] == entry["destination_name"]]
                        if len(matches) != 1:
                            raise ValueError("存档中的令咒目的地无法唯一匹配")
                        arguments["destination_id"] = matches[0]["position_id"]
                    self.session.command_spell("gm", **arguments)
                    break
                if state in self.session.TERMINAL_STATES:
                    raise ValueError("存档重放时游戏提前结束")
                time.sleep(0.005)
            else:
                self.session.stop()
                raise ValueError("存档重放超时")
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if self.session.state == "ready":
                return
            if self.session.state in self.session.TERMINAL_STATES:
                break
            time.sleep(0.005)
        raise ValueError("存档未停在安全节点")

    def _refresh_live_view(self):
        if self.session is None:
            return
        snapshot = self.session.get_snapshot("gm")
        self.ui.globalTurnLabel.setText(f"全局回合：{snapshot['turn']}")
        self.live_scene.set_document(self.map_document)
        self.live_scene.show_characters(self.characters, self.location_ids)

    def _reset_game_page(self):
        self.ui.nextTurnButton.setEnabled(False)
        self.ui.saveGameButton.setEnabled(False)
        self._clear_decision("当前没有需要处理的决定")

    def _clear_decision(self, message):
        self.ui.currentRequestLabel.setText("等待游戏流程")
        self.ui.decisionPromptLabel.setText(message)
        self.ui.decisionOptionList.clear()
        self.ui.decisionConfirmButton.setEnabled(False)
        self.ui.decisionBackButton.setEnabled(False)

    def _append_log(self, message):
        if message:
            self.ui.gameLogEdit.append(str(message))

    def _actor_id(self, value):
        exact = [actor for actor in self.characters if actor.character_id == value]
        if exact:
            return exact[0].character_id
        names = [actor for actor in self.characters if actor.name == value]
        if len(names) != 1:
            raise ValueError("角色参数必须是唯一名称或内部ID")
        return names[0].character_id

    def _actor_name(self, character_id):
        return next((actor.name for actor in self.characters if actor.character_id == character_id), character_id)

    def _position_id(self, value):
        snapshot = self.session.get_snapshot("gm")
        matches = [item for item in snapshot["positions"] if item["position_id"] == value or item["name"] == value]
        if len(matches) != 1:
            raise ValueError("地点参数必须是唯一名称或位置ID")
        return matches[0]["position_id"]

    @staticmethod
    def _positive_int(text, name, *, minimum):
        try:
            value = int(text)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name}必须是整数") from error
        if value < minimum:
            raise ValueError(f"{name}不能小于{minimum}")
        return value

    def _allocate_character_id(self):
        character_id = f"character{self.next_character_number}"
        self.next_character_number += 1
        return character_id

    def _error(self, error):
        QMessageBox.warning(self, "操作未完成", str(error))

    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return
        if self.session is not None and self.session.state not in self.session.TERMINAL_STATES:
            if QMessageBox.question(self, "退出", "游戏仍在运行，确定退出吗？") != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.session.stop()
            self.session.join(2)
        self.poll_timer.stop()
        self._catalog_context.__exit__(None, None, None)
        self._closing = True
        event.accept()
