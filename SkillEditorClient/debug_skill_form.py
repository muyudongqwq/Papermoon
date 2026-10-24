"""A form adapter only for the built-in 测试程序 class skill."""

from copy import deepcopy
from tkinter import ttk

from SkillEditorClient.forms import SkillForm
from SkillEditorClient.model import can_use_form


def can_use_debug_form(category, key, definition):
    if category != "class_skill" or key != "测试程序":
        return False
    if set(definition) != {"name", "ranks"} or definition["name"] != key:
        return False
    ranks = definition["ranks"]
    return isinstance(ranks, dict) and bool(ranks) and all(
        isinstance(rank, str) and can_use_form({"skill_id": key, "components": components})
        for rank, components in ranks.items()
    )


class DebugSkillForm(ttk.Frame):
    def __init__(self, parent, definition, catalogs=None):
        super().__init__(parent)
        self.original = deepcopy(definition)
        self.rank_forms = {}
        ttk.Label(self, text=definition["name"], font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=4)
        for rank, components in definition["ranks"].items():
            group = ttk.LabelFrame(self, text=f"等级 {rank}", padding=6)
            group.pack(fill="x", pady=5)
            form = SkillForm(group, {"skill_id": definition["name"], "name": definition["name"],
                                     "rank": rank, "components": components}, catalogs)
            # Class skills store only components under each rank. Do not expose
            # ordinary skill metadata that cannot be saved in that schema.
            for child in form.winfo_children():
                if child not in (form.component_rows, form.component_controls):
                    child.pack_forget()
            form.pack(fill="x")
            self.rank_forms[rank] = form

    @property
    def components(self):
        return [component for form in self.rank_forms.values() for component in form.components]

    def collapse_all(self):
        for form in self.rank_forms.values():
            form.collapse_all()

    def read(self):
        result = deepcopy(self.original)
        result["ranks"] = {rank: [component.read() for component in form.components]
                           for rank, form in self.rank_forms.items()}
        return result

    def snapshot(self):
        return tuple((rank, form.snapshot()) for rank, form in self.rank_forms.items())
