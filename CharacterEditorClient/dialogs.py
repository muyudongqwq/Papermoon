"""New cards ask for type and class, never a user-entered ID."""

import tkinter as tk
from tkinter import ttk, messagebox
from game.character.servants import VALID_SERVANT_CLASSES


class NewCardDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("新建角色卡")
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="角色类型").grid(row=0, column=0, sticky="w", pady=5)
        self.kind = tk.StringVar(self, value="Master")
        ttk.Combobox(body, textvariable=self.kind, values=("Master", "Servant"), state="readonly", width=22).grid(row=0, column=1, padx=8)
        self.class_row = ttk.Frame(body)
        self.class_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(self.class_row, text="从者职介").pack(side="left")
        self.servant_class = tk.StringVar(self)
        self.class_box = ttk.Combobox(self.class_row, textvariable=self.servant_class, values=tuple(VALID_SERVANT_CLASSES), state="readonly", width=22)
        self.class_box.pack(side="right", padx=8)
        ttk.Label(body, text="角色ID将自动分配。", padding=(0, 8)).grid(row=2, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="开始", command=self.accept).pack(side="left", padx=4)
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="left")
        self.kind.trace_add("write", lambda *_: self.update_kind())
        self.update_kind()
        self.bind("<Return>", lambda _: self.accept())
        self.bind("<Escape>", lambda _: self.destroy())
        self.grab_set()

    def update_kind(self):
        if self.kind.get() == "Servant":
            self.class_row.grid()
        else:
            self.class_row.grid_remove()

    def accept(self):
        if self.kind.get() not in {"Master", "Servant"} or (self.kind.get() == "Servant" and self.servant_class.get() not in VALID_SERVANT_CLASSES):
            messagebox.showerror("角色类型", "请选择合法角色类型；Servant还需要选择职介。", parent=self)
            return
        self.result = (self.kind.get().lower(), self.servant_class.get() if self.kind.get() == "Servant" else None)
        self.destroy()


def ask_new_card(parent):
    dialog = NewCardDialog(parent)
    parent.wait_window(dialog)
    return dialog.result
