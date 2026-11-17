"""Character attributes and bounded selections from the shared skill library."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from CharacterEditorClient.model import (
    ATTRIBUTE_NAMES, ATTRIBUTE_RANKS, FIXED_RANK_CHOICES, class_ranks,
    display_attribute, display_fixed_rank, parse_attribute, parse_fixed_rank, validate_editor_card,
)
from game.character.card_factory import ALIGNMENT_CHOICES, GENDER_CHOICES, initial_noble_limit
from SkillEditorClient.widgets import Collapsible, UNIT_FONT, configure_unit_style, entry_row, request_layout


UNSET = "未设置"
PLUS_CHOICES = ("0", "1", "2")


class LibrarySelection(Collapsible):
    def __init__(self, parent, title, catalog, selected, maximum, *, ranked=False):
        super().__init__(parent, title)
        self.title_text, self.maximum, self.ranked = title, maximum, ranked
        self.on_change = None
        self.rows, self.order = {}, []
        self.search = tk.StringVar(self)
        ttk.Entry(self.body, textvariable=self.search).pack(fill="x", pady=4)
        self.notice = ttk.Label(self.body, wraplength=650)
        self.notice.pack(anchor="w")
        self.area = ttk.Frame(self.body)
        self.area.pack(fill="x")
        state = {item["name"]: item["rank"] for item in selected} if ranked else {key: None for key in selected}
        self.order = list(state)
        self.search.trace_add("write", lambda *_: self.filter())
        self.rebuild(catalog, state)

    def rebuild(self, catalog, state=None):
        if state is None:
            state = {key: row["rank"].get() if self.ranked else None for key, row in self.rows.items() if row["selected"].get()}
        for row in self.rows.values():
            row["frame"].destroy()
        self.rows.clear()
        self.catalog = deepcopy(catalog)
        for key in dict.fromkeys([*catalog, *state]):
            definition = catalog.get(key)
            row = ttk.Frame(self.area)
            row.pack(fill="x", pady=2)
            checked = tk.BooleanVar(self, value=key in state)
            text = f"{definition.get('name', key)} [{key}]" if definition else f"{key}（已不在技能库）"
            if not self.ranked and definition:
                rank = definition.get("rank")
                text += f"  Rank {rank}" if rank else "  随角色宝具等级"
            button = ttk.Checkbutton(row, text=text, variable=checked, command=lambda key=key: self.changed(key))
            button.pack(side="left", fill="x", expand=True)
            ranks = class_ranks(definition) if definition and self.ranked else ()
            default = "C" if "C" in ranks else next(iter(ranks), "")
            rank = tk.StringVar(self, value=state[key] if key in state and self.ranked else default)
            combo = None
            if self.ranked:
                combo = ttk.Combobox(row, textvariable=rank, values=ranks, state="readonly", width=10)
                combo.pack(side="right", padx=5)
                combo.bind("<MouseWheel>", lambda _: "break")
            self.rows[key] = {"frame": row, "selected": checked, "rank": rank, "combo": combo, "button": button, "search_text": text.casefold()}
        self.update_limits()
        self.filter()

    def changed(self, key):
        if self.rows[key]["selected"].get() and key not in self.order:
            self.order.append(key)
        self.update_limits()
        if self.on_change is not None:
            self.on_change()

    def update_limits(self):
        count = sum(row["selected"].get() for row in self.rows.values())
        count_text = str(count) if self.maximum is None else f"{count}/{self.maximum}"
        self.label.configure(text=f"{self.title_text}（{count_text}）")
        limit_text = "" if self.maximum is None else f"最多选择{self.maximum}项。"
        self.notice.configure(text=limit_text + ("每项选择技能库中已有定义的等级。" if self.ranked else "可搜索名称或技能ID。"))
        for row in self.rows.values():
            chosen = row["selected"].get()
            row["button"].configure(state="normal" if chosen or self.maximum is None or count < self.maximum else "disabled")
            if row["combo"] is not None:
                row["combo"].configure(state="readonly" if chosen else "disabled")

    def filter(self):
        term = self.search.get().strip().casefold()
        for row in self.rows.values():
            row["frame"].pack_forget()
            if term in row["search_text"]:
                row["frame"].pack(fill="x", pady=2)
        request_layout(self)

    def read(self):
        keys = [key for key in dict.fromkeys([*self.order, *self.rows]) if key in self.rows and self.rows[key]["selected"].get()]
        return [{"name": key, "rank": self.rows[key]["rank"].get()} for key in keys] if self.ranked else keys

    def snapshot(self):
        return tuple((key, row["rank"].get() if self.ranked else None) for key, row in self.rows.items() if row["selected"].get())


class CharacterForm(ttk.Frame):
    def __init__(self, parent, definition, catalogs, *, new=False):
        initial_attributes = {key: "" if new else display_attribute(definition["attributes"][key]) for key in ATTRIBUTE_NAMES}
        super().__init__(parent)
        configure_unit_style(self)
        self.original, self.catalogs = deepcopy(definition), catalogs
        kind = definition["character_type"]
        ttk.Label(self, text="Master / 御主" if kind == "master" else f"Servant / 从者  ·  {definition['servant_class']}", font=UNIT_FONT).pack(anchor="w", pady=4)
        self.name, _ = entry_row(self, "角色名称", definition.get("name", ""), font=UNIT_FONT)
        self.gender, _ = self.rank_row(
            self, "性别", definition.get("gender", UNSET), (UNSET, *GENDER_CHOICES), editable=False,
        )
        alignment = definition.get("alignment", {})
        order, order_box = self.rank_row(
            self, "阵营", alignment.get("order", UNSET),
            (UNSET, *ALIGNMENT_CHOICES["order"]), editable=False,
        )
        morality = self.append_choice(
            order_box, alignment.get("morality", UNSET), (UNSET, *ALIGNMENT_CHOICES["morality"]),
        )
        self.alignment = {"order": order, "morality": morality}
        attributes = ttk.LabelFrame(self, text="基础属性", padding=8)
        attributes.pack(fill="x", pady=7)
        ttk.Label(attributes, text="每项先选 E～A，再选加符数量 0～2。请填写全部五项。", wraplength=650).pack(anchor="w", pady=3)
        self.attributes = {}
        self.attribute_boxes = {}
        self.attribute_pluses = {}
        for key, label in ATTRIBUTE_NAMES.items():
            value = initial_attributes[key]
            variable, box = self.rank_row(
                attributes, label, value.rstrip("+"), ATTRIBUTE_RANKS, editable=False,
            )
            self.attributes[key], self.attribute_boxes[key] = variable, box
            self.attribute_pluses[key] = self.append_choice(
                box, str(value.count("+")), PLUS_CHOICES, width=4,
            )
        field = "talent" if kind == "master" else "noble"
        self.rank_field = field
        self.rank, self.rank_box = self.rank_row(self, "天赋等级" if kind == "master" else "宝具等级", display_fixed_rank(definition[field]), FIXED_RANK_CHOICES)
        self.classes = self.basic = None
        if kind == "master":
            self.basic = LibrarySelection(self, "基础魔术", catalogs["basic_magic"], definition.get("basic_magics", []), None)
            self.basic.pack(fill="x", pady=5)
        else:
            self.classes = LibrarySelection(self, "职介技能", catalogs["class_skill"], definition.get("class_skills", []), 2, ranked=True)
            self.classes.pack(fill="x", pady=5)
        self.personal = LibrarySelection(self, "固有技能", catalogs["personal_skill"], definition.get("personal_skills", []), 3)
        self.personal.pack(fill="x", pady=5)
        self.nobles = None
        if kind == "servant":
            self.nobles = LibrarySelection(self, "宝具", catalogs["noble_phantasm"],
                                           definition.get("noble_phantasms", []), initial_noble_limit(definition["noble"]))
            self.nobles.pack(fill="x", pady=5)
        self.trump = tk.StringVar(self, value=UNSET)
        trump_row = ttk.Frame(self)
        trump_row.pack(fill="x", pady=5)
        ttk.Label(trump_row, text="底力技").pack(side="left")
        self.trump_box = ttk.Combobox(
            trump_row, textvariable=self.trump, state="readonly", width=52,
        )
        self.trump_box.pack(side="left", padx=(12, 0), fill="x", expand=True)
        self.trump_box.bind("<MouseWheel>", lambda _event: "break")
        self._trump_by_label = {}
        self._trump_label_by_id = {}
        self.refresh_trump_choices(definition.get("hidden_trump"))
        self.personal.on_change = self.refresh_trump_choices
        if self.nobles is None:
            self.placeholder = ttk.LabelFrame(self, text="礼装（预留）", padding=9)
            self.placeholder.pack(fill="x", pady=6)
            ttk.Label(self.placeholder, text="暂未开放礼装选择。").pack(anchor="w")
        else:
            self.nobles.on_change = self.refresh_trump_choices
            self.rank.trace_add("write", self.noble_rank_changed)

    def noble_rank_changed(self, *_):
        try:
            rank = parse_fixed_rank(self.rank.get(), allow_plus=True)
        except ValueError:
            return
        self.nobles.maximum = initial_noble_limit(rank)
        self.nobles.update_limits()
        self.refresh_trump_choices()

    @staticmethod
    def rank_row(parent, label, value, choices, *, editable=True):
        variable, box = entry_row(parent, label, value, choices=choices, editable=editable)
        box.pack_configure(fill="none", expand=False)
        box.configure(width=7)
        return variable, box

    @staticmethod
    def append_choice(first_box, value, choices, *, width=7):
        row = first_box.master
        variable = tk.StringVar(master=row, value=value)
        box = ttk.Combobox(row, textvariable=variable, values=choices, state="readonly", width=width)
        box.pack(side="left", padx=(8, 0), after=first_box)
        box.bind("<MouseWheel>", lambda _event: "break")
        return variable

    def update_catalogs(self, catalogs):
        self.catalogs = catalogs
        if self.classes is not None:
            self.classes.rebuild(catalogs["class_skill"])
        if self.basic is not None:
            self.basic.rebuild(catalogs["basic_magic"])
        self.personal.rebuild(catalogs["personal_skill"])
        if self.nobles is not None:
            self.nobles.rebuild(catalogs["noble_phantasm"])
        self.refresh_trump_choices()

    def refresh_trump_choices(self, preferred_id=None):
        if preferred_id is None:
            preferred_id = self._trump_by_label.get(self.trump.get())
        candidate_ids = list(self.personal.read())
        if self.nobles is not None:
            candidate_ids.extend(self.nobles.read())
        legacy_trump = (preferred_id == self.original.get("hidden_trump")
                        and preferred_id not in self.original.get("noble_phantasms", []))
        if preferred_id and (preferred_id not in self.catalogs["noble_phantasm"] or legacy_trump):
            candidate_ids.append(preferred_id)
        by_label = {}
        label_by_id = {}
        for content_id in dict.fromkeys(candidate_ids):
            definition = self.catalogs["personal_skill"].get(content_id)
            category = "personal_skill"
            if definition is None and self.nobles is not None:
                definition = self.catalogs["noble_phantasm"].get(content_id)
                category = "noble_phantasm"
            if definition is None:
                continue
            rank = definition.get("rank", self.rank.get().strip().removesuffix("+"))
            if rank == "EX":
                continue
            kind_label = "技能" if category == "personal_skill" else "宝具"
            label = f"{kind_label}：{definition.get('name', content_id)} [{content_id}]"
            by_label[label] = content_id
            label_by_id[content_id] = label
        self._trump_by_label = by_label
        self._trump_label_by_id = label_by_id
        self.trump_box.configure(values=(UNSET, *by_label))
        self.trump.set(label_by_id.get(preferred_id, UNSET))

    def read(self):
        data = deepcopy(self.original)
        data["name"] = self.name.get().strip()
        gender = self.gender.get()
        if gender == UNSET:
            data.pop("gender", None)
        else:
            data["gender"] = gender
        alignment = {
            axis: variable.get()
            for axis, variable in self.alignment.items() if variable.get() != UNSET
        }
        if alignment:
            data["alignment"] = alignment
        else:
            data.pop("alignment", None)
        for key, variable in self.attributes.items():
            grade, plus = variable.get(), self.attribute_pluses[key].get()
            if grade not in ATTRIBUTE_RANKS or plus not in PLUS_CHOICES:
                raise ValueError(f"{ATTRIBUTE_NAMES[key]}：请选择 E～A 和加符数量 0～2")
            displayed = grade + "+" * int(plus)
            if displayed != display_attribute(data["attributes"][key]):
                data["attributes"][key] = parse_attribute(displayed)
        parsed_rank = parse_fixed_rank(self.rank.get(), allow_plus=self.rank_field == "noble")
        if self.rank.get().strip() != display_fixed_rank(self.original[self.rank_field]):
            data[self.rank_field] = parsed_rank
        data["class_skills"] = self.classes.read() if self.classes is not None else []
        if self.basic is not None:
            data["basic_magics"] = self.basic.read()
        data["personal_skills"] = self.personal.read()
        if self.nobles is not None:
            data["noble_phantasms"] = self.nobles.read()
        hidden_trump = self._trump_by_label.get(self.trump.get())
        if hidden_trump is None:
            data.pop("hidden_trump", None)
        else:
            data["hidden_trump"] = hidden_trump
        return validate_editor_card(data, self.catalogs)

    def snapshot(self):
        return (self.name.get(), tuple(variable.get() for variable in self.attributes.values()), self.rank.get(),
                tuple(variable.get() for variable in self.attribute_pluses.values()),
                self.gender.get(), tuple(variable.get() for variable in self.alignment.values()),
                self.classes.snapshot() if self.classes is not None else None,
                self.basic.snapshot() if self.basic is not None else None, self.personal.snapshot(),
                self.nobles.snapshot() if self.nobles is not None else None,
                self.trump.get())
