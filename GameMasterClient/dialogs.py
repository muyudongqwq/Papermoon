"""Small dialogs backed by the Designer files."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidgetItem, QPushButton

from GameMasterClient.ui_characterstatus import Ui_characterStatusDialog
from GameMasterClient.ui_groupmanager import Ui_groupEditorDialog
from game.game.character_state import character_state


class GroupEditorDialog(QDialog):
    def __init__(self, characters, group=None, parent=None):
        super().__init__(parent)
        self.ui = Ui_groupEditorDialog()
        self.ui.setupUi(self)
        self.characters = list(characters)
        selected = set(group.get("member_ids", ())) if group else set()
        self.ui.groupNameEdit.setText(group.get("name", "") if group else "")
        for actor in self.characters:
            item = QListWidgetItem(f"{actor.name}  [{actor.character_id}]")
            item.setData(Qt.ItemDataRole.UserRole, actor.character_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if actor.character_id in selected else Qt.CheckState.Unchecked)
            self.ui.groupMemberContent.addItem(item)

    def value(self):
        name = self.ui.groupNameEdit.text().strip()
        members = [self.ui.groupMemberContent.item(index).data(Qt.ItemDataRole.UserRole)
                   for index in range(self.ui.groupMemberContent.count())
                   if self.ui.groupMemberContent.item(index).checkState() == Qt.CheckState.Checked]
        if not name:
            raise ValueError("分组名称不能为空")
        if not members:
            raise ValueError("分组至少需要一名成员")
        return {"name": name, "member_ids": members}


class CharacterStatusDialog(QDialog):
    def __init__(self, character, parent=None, command_spell_callback=None,
                 decision_request=None, decision_callback=None):
        super().__init__(parent)
        self.ui = Ui_characterStatusDialog()
        self.ui.setupUi(self)
        self.character = character
        self.command_spell_callback = command_spell_callback
        self.decision_request = decision_request
        self.decision_callback = decision_callback
        self.ui.closeButton.clicked.connect(self.accept)
        self.refresh()

    def refresh(self):
        actor = self.character
        state = character_state(actor)
        self.ui.characterNameLabel.setText(f"{actor.name}  [{actor.character_id}]")
        self.ui.hpLabel.setText(f"HP：{actor.hp:g} / {actor.hpmax:g}")
        self.ui.hpProgressBar.setRange(0, max(1, int(actor.hpmax)))
        self.ui.hpProgressBar.setValue(max(0, int(actor.hp)))
        total_mp = actor.mp + actor.temporary_mp
        self.ui.mpLabel.setText(f"MP：{total_mp:g} / {actor.mpmax:g}")
        self.ui.mpProgressBar.setRange(0, max(1, int(actor.mpmax)))
        self.ui.mpProgressBar.setValue(max(0, int(min(total_mp, actor.mpmax))))
        self.ui.locationLabel.setText(f"位置：{getattr(actor.position, 'name', '无')}")
        self.ui.phaseLabel.setText(f"全局回合：{actor.current_global_turn}")
        self.ui.isBattleLabel.setText("战斗状态：战斗中" if actor.in_battle else "战斗状态：战斗外")
        self.ui.statusListWidget.clear()
        for status in state["status_instances"]:
            self.ui.statusListWidget.addItem(status.get("name", status.get("status_id", "状态")))
        if not state["status_instances"]:
            self.ui.statusListWidget.addItems(sorted(actor.status_flags) or ["无状态"])
        layout = self.ui.actionButtonLayout
        for index in reversed(range(layout.count())):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        row = 0
        if self.command_spell_callback is not None and hasattr(actor, "command_spell"):
            button = QPushButton(f"令咒（{actor.command_spell}划）")
            button.clicked.connect(lambda: self.command_spell_callback(actor))
            layout.addWidget(button, 0, 0, 1, 2)
            row = 2
        if (self.decision_request is not None
                and self.decision_request.get("kind") == "choice"
                and self.decision_request.get("character_id") == actor.character_id):
            for option in self.decision_request["options"]:
                button = QPushButton(option["label"])
                button.clicked.connect(
                    lambda _checked=False, option_id=option["option_id"]:
                    self._choose_decision(option_id)
                )
                layout.addWidget(button, row // 2, row % 2)
                row += 1
            return
        for skill in state["skills"]:
            button = QPushButton(skill["name"])
            button.setToolTip(skill.get("description") or "暂无说明")
            button.clicked.connect(lambda _checked=False, entry=skill: self._show_skill(entry))
            layout.addWidget(button, row // 2, row % 2)
            row += 1

    def _choose_decision(self, option_id):
        if self.decision_callback is not None:
            self.decision_callback(option_id)
            self.accept()

    def _show_skill(self, skill):
        page = self.ui.actionDetailPage
        label = page.findChild(type(self.ui.characterNameLabel), "runtimeSkillDetail")
        if label is None:
            from PySide6.QtWidgets import QLabel, QVBoxLayout
            if page.layout() is None:
                page.setLayout(QVBoxLayout())
            label = QLabel(page)
            label.setObjectName("runtimeSkillDetail")
            label.setWordWrap(True)
            page.layout().addWidget(label)
        label.setText(f"{skill['name']}  {skill['rank']}\n\n{skill.get('description') or '暂无说明'}")
        self.ui.actionDetailStack.setCurrentWidget(page)
