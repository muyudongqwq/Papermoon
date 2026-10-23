"""Read-only effect reference sourced from engine schemas and the dictionary."""

import re
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from game.skill.effect_validation import EFFECT_SCHEMAS
from SkillEditorClient.effect_options import (
    EFFECT_NAMES, FORM_EFFECT_TYPES as EFFECT_TYPES, FIELD_NAMES,
    parameter_options, parameter_spec, editor_effect_schema,
)


DICTIONARY_PATH = Path(__file__).resolve().with_name("effect_dictionary.txt")


def read_dictionary():
    return DICTIONARY_PATH.read_text(encoding="utf-8-sig")


def dictionary_sections(text):
    """Extract numbered effect headings and the dictionary's bare Modifier headings."""
    lines = text.splitlines()
    headings = [index for index in range(len(lines) - 1)
                if lines[index].strip() and re.fullmatch(r"[-=]{3,}", lines[index + 1].strip())]
    sections = {}
    for offset, index in enumerate(headings):
        end = headings[offset + 1] if offset + 1 < len(headings) else len(lines)
        names = set(re.findall(r"[a-z][a-z0-9_]*", lines[index])) & set(EFFECT_TYPES)
        for name in names:
            sections.setdefault(name, []).append("\n".join(lines[index:end]).strip())
    bare = [index for index, line in enumerate(lines) if line in EFFECT_SCHEMAS]
    for index in bare:
        end = min((boundary for boundary in [*headings, *bare, len(lines)] if boundary > index))
        sections.setdefault(lines[index], []).append("\n".join(lines[index:end]).strip())
    return {name: "\n\n".join(blocks) for name, blocks in sections.items()}


def modifier_reference(text):
    match = re.search(r"^八、Modifier公共字段\s*\n[=]+\s*\n(.*?)(?=^九、)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def reference_text(effect_type, text, catalogs=None):
    schema = editor_effect_schema(effect_type)
    result = [f"{effect_type} · {EFFECT_NAMES.get(effect_type, effect_type)}",
              "编辑器结构入口（保存为技能单元的choices）" if effect_type == "choices" else
              ("持续效果（Modifier）" if schema.modifier else "即时效果"),
              "", "对应的 effect_data 参数"]
    if not schema.allowed_data:
        result.append("此效果没有独立参数，使用空对象 {}。")
    for key in parameter_options(effect_type):
        required = "必填" if key in schema.required_data else "可选"
        label = FIELD_NAMES.get(key)
        result.append(f"  {key}" + (f"（{label}）" if label else "") + f"　[{required}]")
        spec = parameter_spec(effect_type, key, catalogs)
        if spec.choices:
            result.append("      编辑器候选值：" + " | ".join(spec.choices))
    result.extend(["", "以上为固定必填项；条件必填、互斥字段、默认值和数值范围见下方说明。",
                   "", "效果说明（来自内置效果字典）", "",
                   dictionary_sections(text).get(effect_type, "此效果尚无独立说明，请查看完整效果字典。")])
    if schema.modifier:
        result.extend(["", "持续效果的公共字段（放在 effect 顶层，不放进 effect_data）", "",
                       modifier_reference(text)])
    return "\n".join(result)


class EffectReferenceWindow(tk.Toplevel):
    def __init__(self, parent, effect_type=None, catalogs=None):
        super().__init__(parent)
        self.withdraw()
        self.title("Papermoon · 效果参考（只读）")
        self.geometry("1040x720")
        self.minsize(760, 480)
        self.transient(parent)
        self.catalogs = catalogs
        self.dictionary = read_dictionary()
        self.documents = dictionary_sections(self.dictionary)
        self.current_effect = None
        self.search_index = {kind: f"{kind} {EFFECT_NAMES.get(kind, '')} {' '.join(parameter_options(kind))} {self.documents.get(kind, '')}".casefold()
                             for kind in EFFECT_TYPES}
        self.search = tk.StringVar(master=self)
        toolbar = ttk.Frame(self, padding=8)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="搜索类型、中文名称、参数或说明").pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search)
        self.search_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="清空", command=lambda: self.search.set("")).pack(side="left", padx=5)
        self.count = ttk.Label(toolbar)
        self.count.pack(side="right")
        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        self.listbox = tk.Listbox(left, exportselection=False, width=35, font=("Microsoft YaHei UI", 10))
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text = ScrolledText(right, wrap="word", font=("Microsoft YaHei UI", 10), state="disabled", padx=8, pady=8)
        self.text.pack(fill="both", expand=True)
        ttk.Label(self, text="只读参考，可选择文字并按 Ctrl+C 复制；内容不会写入技能项目。", padding=8).pack(fill="x")
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.search.trace_add("write", lambda *_: self.refresh())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.select_effect(effect_type)
        self.deiconify()

    def set_text(self, text):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def refresh(self):
        term = self.search.get().strip().casefold()
        self.visible_effects = [kind for kind in EFFECT_TYPES if not term or term in self.search_index[kind]]
        self.listbox.delete(0, "end")
        for kind in self.visible_effects:
            self.listbox.insert("end", f"{EFFECT_NAMES.get(kind, kind)} [{kind}]")
        self.count.configure(text=f"{len(self.visible_effects)} / {len(EFFECT_TYPES)}")
        if not self.visible_effects:
            self.current_effect = None
            self.set_text("没有找到匹配的效果。")
            return
        kind = self.current_effect if self.current_effect in self.visible_effects else self.visible_effects[0]
        index = self.visible_effects.index(kind)
        self.listbox.selection_set(index)
        self.listbox.see(index)
        self.render(kind)

    def render(self, kind):
        self.current_effect = kind
        self.set_text(reference_text(kind, self.dictionary, self.catalogs))

    def on_select(self, _event=None):
        selected = self.listbox.curselection()
        if selected:
            self.render(self.visible_effects[selected[0]])

    def select_effect(self, effect_type=None, catalogs=None):
        if catalogs is not None:
            self.catalogs = catalogs
        if effect_type in EFFECT_TYPES:
            self.current_effect = effect_type
        self.search.set("")
        self.refresh()


def show_effect_reference(widget, effect_type=None, catalogs=None):
    parent = widget.winfo_toplevel()
    window = getattr(parent, "_effect_reference_window", None)
    if window is None or not window.winfo_exists():
        window = EffectReferenceWindow(parent, effect_type, catalogs)
        parent._effect_reference_window = window
    else:
        window.select_effect(effect_type, catalogs)
        window.deiconify()
    window.lift()
    return window
