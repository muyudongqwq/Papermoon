"""Collapsible groups and local scrolling used by the experimental editor."""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from SkillEditorClient.model import PHASES, PHASE_LABELS
from skilleditor.documents import format_json


def request_layout(widget):
    """Refresh the enclosing canvas after its content changes size."""
    parent = widget
    while parent is not None:
        if isinstance(parent, ScrollForm):
            parent.refresh_later()
            return
        parent = parent.master


def combobox_placeholder(widget, variable, text):
    """Display a hint without putting it in the form's saved value."""
    display = tk.StringVar(widget)
    widget.configure(textvariable=display)
    widget.placeholder_display = display
    changing = False

    def render(*_):
        nonlocal changing
        if changing:
            return
        changing = True
        try:
            # The ttk popdown exists only in Tcl; focus_get() attempts to
            # resolve it as a Python widget and raises KeyError('popdown').
            focused = str(widget.tk.call("focus")) == str(widget)
            display.set(variable.get() or ("" if focused else text))
        finally:
            changing = False

    def edited(*_):
        if not changing:
            variable.set("" if display.get() == text else display.get())

    variable.trace_add("write", render)
    display.trace_add("write", edited)
    widget.bind("<FocusIn>", render, add=True)
    widget.bind("<FocusOut>", render, add=True)
    render()


class Collapsible(ttk.Frame):
    def __init__(self, parent, title, *, expanded=False, font=None, button_style="TButton"):
        super().__init__(parent, padding=(3, 2))
        self.expanded = expanded
        self.header = ttk.Frame(self)
        self.header.pack(fill="x")
        self.toggle_button = ttk.Button(self.header, width=2, command=self.toggle, style=button_style)
        self.toggle_button.pack(side="left")
        self.label = ttk.Label(self.header, text=title, **({"font": font} if font is not None else {}))
        self.label.pack(side="left", padx=5)
        self.label.bind("<Button-1>", lambda _event: self.toggle())
        self.body = ttk.Frame(self, padding=(16, 5, 0, 5))
        self.render()

    def render(self):
        self.toggle_button.configure(text="−" if self.expanded else "+")
        if self.expanded:
            self.body.pack(fill="x")
        else:
            self.body.pack_forget()
        request_layout(self)

    def toggle(self):
        self.expanded = not self.expanded
        self.render()


class JsonBox(ttk.Frame):
    def __init__(self, parent, value, *, height=4):
        super().__init__(parent)
        self.text = ScrolledText(self, height=height, wrap="none", undo=True, font=("Consolas", 11))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", format_json(value))
        self.text.edit_reset()
        scroll = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(xscrollcommand=scroll.set)
        scroll.pack(fill="x")

    def get(self):
        return self.text.get("1.0", "end-1c")


PHASE_BACKGROUND = "#e4e4e4"
SECTION_SEPARATOR_COLOR = "#707070"
SECTION_SEPARATOR_HEIGHT = 2
UNIT_FONT = ("Microsoft YaHei UI", 12)


def configure_unit_style(widget):
    ttk.Style(widget).configure("NewSkillUnit.TButton", font=UNIT_FONT, padding=(8, 5))


def configure_gray_area(widget):
    style = ttk.Style(widget)
    style.configure("PhaseArea.TFrame", background=PHASE_BACKGROUND)
    style.configure("PhaseArea.TLabel", background=PHASE_BACKGROUND)
    style.configure("PhaseArea.TCheckbutton", background=PHASE_BACKGROUND)
    style.map("PhaseArea.TCheckbutton", background=[("active", PHASE_BACKGROUND)])
    style.configure("EffectData.TNotebook", background=PHASE_BACKGROUND)


class PhaseSelect(ttk.Frame):
    def __init__(self, parent, phases, changed):
        configure_gray_area(parent)
        super().__init__(parent, style="PhaseArea.TFrame")
        self.order = list(dict.fromkeys([*phases, *PHASES]))
        self.variables = {p: tk.BooleanVar(master=self, value=p in phases) for p in self.order}
        self.buttons = {}
        self.columns = None
        for index, phase in enumerate(self.order):
            button = ttk.Checkbutton(self, text=PHASE_LABELS.get(phase, phase), variable=self.variables[phase], command=lambda: self.selected(changed), style="PhaseArea.TCheckbutton")
            button.grid(row=index // 3, column=index % 3, sticky="w", padx=(0, 8), pady=2)
            self.buttons[phase] = button
        self.bind("<Configure>", self.layout)

    def layout(self, event):
        required = max((button.winfo_reqwidth() + 8 for button in self.buttons.values()), default=1)
        columns = max(1, min(3, event.width // required))
        if columns == self.columns:
            return
        self.columns = columns
        for index in range(3):
            self.columnconfigure(index, weight=1 if index < columns else 0)
        for index, button in enumerate(self.buttons.values()):
            button.grid_configure(row=index // columns, column=index % columns)
        request_layout(self)

    def get(self):
        return [p for p in self.order if self.variables[p].get()]

    def selected(self, changed):
        changed()


class ScrollForm(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.layout_job = None
        self.refreshing_layout = False
        self.canvas = tk.Canvas(self, highlightthickness=0, background=ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=8)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self.sync_scrollregion)
        self.canvas.bind("<Configure>", self.resize)
        self.wheel_binding = self.winfo_toplevel().bind("<MouseWheel>", self.wheel, add="+")
        self.bind("<Destroy>", self.on_destroy)

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        self.sync_scrollregion()

    def refresh_later(self):
        if self.layout_job is None and not self.refreshing_layout:
            self.layout_job = self.after_idle(self.refresh_layout)

    def refresh_layout(self):
        self.layout_job = None
        self.refreshing_layout = True
        try:
            # Geometry propagation takes several idle steps. An off-screen
            # canvas window may otherwise keep its old height and viewport.
            self.update_idletasks()
            self.sync_scrollregion()
        finally:
            self.refreshing_layout = False

    def sync_scrollregion(self, _event=None):
        bounds = self.canvas.bbox(self.window)
        if bounds is None:
            return
        self.canvas.configure(scrollregion=bounds)
        height = bounds[3] - bounds[1]
        viewport = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if height <= viewport or top < bounds[1]:
            self.canvas.yview_moveto(0)
        elif top > bounds[3] - viewport:
            self.canvas.yview_moveto((height - viewport) / height)

    def wheel(self, event):
        if not str(event.widget).startswith(str(self)) or isinstance(event.widget, tk.Text):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def on_destroy(self, event):
        if event.widget is self:
            if self.layout_job is not None:
                self.after_cancel(self.layout_job)
            if self.wheel_binding:
                self.winfo_toplevel().unbind("<MouseWheel>", self.wheel_binding)


def entry_row(parent, label, value="", *, choices=None, editable=True, compact=False, font=None):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=3)
    label_options = {"font": font} if font is not None else {}
    ttk.Label(row, text=label, width=22, **label_options).pack(side="left", anchor="n")
    area = row
    if compact:
        area = ttk.Frame(row)
        area.pack(side="left", fill="x", expand=True)
        area.columnconfigure(0, weight=1, uniform="halves")
        area.columnconfigure(1, weight=1, uniform="halves")
    variable = tk.StringVar(master=row, value=value)
    widget = (ttk.Entry(area, textvariable=variable) if choices is None else
              ttk.Combobox(area, textvariable=variable, values=choices, state="normal" if editable else "readonly"))
    if font is not None:
        widget.configure(font=font)
    if compact:
        widget.grid(row=0, column=0, sticky="ew")
    else:
        widget.pack(side="left", fill="x", expand=True)
    if isinstance(widget, ttk.Combobox):
        widget.bind("<MouseWheel>", lambda _event: "break")
    return variable, widget
