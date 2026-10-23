"""Small localized dialogs for the client; the original editor is unchanged."""

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from game.rank.rank import SkillRank
from SkillEditorClient.model import RANKS


class NewSkillDialog(simpledialog.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="新建技能")

    def body(self, parent):
        self.name = tk.StringVar(master=self)
        self.rank = tk.StringVar(master=self, value="C")
        ttk.Label(parent, text="名称").grid(row=0, column=0, sticky="w", padx=5, pady=6)
        self.name_box = ttk.Entry(parent, textvariable=self.name, width=20)
        self.name_box.grid(row=0, column=1, padx=5, pady=6)
        ttk.Label(parent, text="Rank").grid(row=1, column=0, sticky="w", padx=5, pady=6)
        self.rank_box = ttk.Combobox(parent, textvariable=self.rank, values=RANKS, width=18)
        self.rank_box.grid(row=1, column=1, padx=5, pady=6)
        self.rank_box.bind("<MouseWheel>", lambda _event: "break")
        return self.name_box

    def buttonbox(self):
        buttons = ttk.Frame(self, padding=(5, 5, 5, 10))
        self.start_button = ttk.Button(buttons, text="开始", command=self.ok, width=8)
        self.start_button.pack(side="left", padx=5)
        self.cancel_button = ttk.Button(buttons, text="取消", command=self.cancel, width=8)
        self.cancel_button.pack(side="left", padx=5)
        buttons.pack()
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        if not self.name.get().strip():
            messagebox.showerror("尚未填写完整", "请填写技能名称。", parent=self)
            self.name_box.focus_set()
            return False
        try:
            SkillRank(self.rank.get().strip())
        except ValueError:
            messagebox.showerror("Rank无效", "请选择或填写合法的Rank：" + "、".join((*RANKS, "GM")), parent=self)
            self.rank_box.focus_set()
            return False
        return True

    def apply(self):
        self.result = self.name.get().strip(), self.rank.get().strip()


def ask_new_skill(parent):
    return NewSkillDialog(parent).result
