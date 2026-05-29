from __future__ import annotations

from collections import OrderedDict
import queue
import threading
from pathlib import Path
from typing import Any
from tkinter import BooleanVar, DoubleVar, IntVar, StringVar, TclError, Tk, filedialog, messagebox
from tkinter import Canvas, Frame, Label, Listbox, Scrollbar, Text
from tkinter import ttk

from PIL import Image, ImageTk

from .effects import EFFECT_LABELS, EffectStep, apply_effect, make_effect
from .lospec import LospecClient
from .models import Palette
from .processor import histogram_rgb, image_statistics, save_palette_gpl, save_palette_png


BG = "#f7f8fa"
PANEL = "#ffffff"
PANEL_MUTED = "#f2f5f8"
TEXT = "#172033"
MUTED = "#687385"
BORDER = "#e5eaf0"
ACCENT = "#2563eb"
ACCENT_DARK = "#1d4ed8"
ACCENT_SOFT = "#e8f0ff"
CANVAS_BG = "#fbfcfe"
PREVIEW_MAX_EDGE = 1200


def display_image_size(image_size: tuple[int, int], bounds: tuple[int, int]) -> tuple[int, int]:
    image_width, image_height = image_size
    bound_width, bound_height = bounds
    if image_width <= 0 or image_height <= 0:
        return 1, 1
    scale = min(max(1, bound_width) / image_width, max(1, bound_height) / image_height)
    return max(1, int(round(image_width * scale))), max(1, int(round(image_height * scale)))


class ColorUtilsApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("ColorUtils - Effect Stack")
        self.root.geometry("1360x840")
        self.root.minsize(1100, 720)

        self.client = LospecClient()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self.source_image: Image.Image | None = None
        self.preview_image: Image.Image | None = None
        self.result_image: Image.Image | None = None
        self.source_version = 0
        self.image_path: Path | None = None
        self.original_photo: ImageTk.PhotoImage | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.original_photo_key: tuple[Any, ...] | None = None
        self.preview_photo_key: tuple[Any, ...] | None = None
        self.original_canvas_items: tuple[int, int] | None = None
        self.preview_canvas_items: tuple[int, int] | None = None
        self.preview_source_cache_key: tuple[Any, ...] | None = None
        self.preview_source_cache: Image.Image | None = None

        self.effect_steps: list[EffectStep] = []
        self.selected_step_index: int | None = None
        self.drag_index: int | None = None
        self.param_vars: list[object] = []
        self.stack_row_widgets: list[Frame] = []

        self.palettes: list[Palette] = []
        self.current_palette: Palette | None = None
        self.palette_list: Listbox | None = None
        self.palette_page = -1
        self.palette_total = 0
        self.palette_loading = False
        self.palette_mode = "list"

        self.status_var = StringVar(value="Loading cached Lospec palettes...")
        self.image_info_var = StringVar(value="No image opened")
        self.palette_search_var = StringVar()
        self.palette_sort_var = StringVar(value="default")
        self.sharp_preview_var = BooleanVar(value=False)

        self.preview_token = 0
        self.preview_cache: OrderedDict[tuple[Any, ...], tuple[Image.Image, int]] = OrderedDict()
        self.preview_cache_limit = 48
        self.preview_cache_max_bytes = 512 * 1024 * 1024
        self.preview_cache_bytes = 0
        self.preview_cache_lock = threading.Lock()
        self.palette_search_token = 0
        self.palette_search_after_id: str | None = None
        self.stack_after_id: str | None = None
        self.resize_after_id: str | None = None
        self.preview_rendering = False
        self.preview_pending = False
        self.stats_token = 0

        self.operation_kinds = [
            "lospec",
            "pixelize",
            "pixel_perfect",
            "color_adjust",
            "contrast",
            "gamma",
            "threshold",
            "posterize",
            "invert",
            "gaussian3",
            "box_blur",
            "laplace",
            "sobel",
            "dog",
            "edge_enhance",
            "sharpen",
            "unsharp",
            "emboss",
            "median",
            "erosion",
            "dilation",
            "opening",
            "closing",
            "morph_gradient",
        ]

        self._configure_style()
        self._build_ui()
        self._bind_events()
        self._poll_events()
        self.load_palettes(reset=True)

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", padding=(18, 9), background=PANEL_MUTED, foreground=MUTED, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", TEXT)])
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
            focuscolor=ACCENT,
            padding=(16, 9),
        )
        style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("disabled", "#9eb6ef")])
        style.configure("TButton", background=PANEL_MUTED, foreground=TEXT, borderwidth=0, focusthickness=0, padding=(12, 8))
        style.map("TButton", background=[("active", "#e9eef5"), ("disabled", "#f5f7fa")])
        style.configure("Stack.TButton", background="#f3f6fa", foreground=TEXT, borderwidth=0, padding=(8, 5))
        style.map("Stack.TButton", background=[("active", "#e9eef5"), ("disabled", "#f7f9fb")])
        style.configure("Danger.TButton", background="#fff1f2", foreground="#be123c", borderwidth=0, padding=(8, 5))
        style.map("Danger.TButton", background=[("active", "#fecaca")])
        style.configure("On.TButton", background="#ecfdf5", foreground="#047857", borderwidth=0, padding=(8, 5))
        style.map("On.TButton", background=[("active", "#d1fae5")])
        style.configure("Off.TButton", background="#f3f6fa", foreground=MUTED, borderwidth=0, padding=(8, 5))
        style.map("Off.TButton", background=[("active", "#e9eef5")])
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(8, 7))
        style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(8, 7))
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
        style.configure("Horizontal.TScale", background=BG)
        style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL_MUTED, borderwidth=0, lightcolor=ACCENT, darkcolor=ACCENT)

    def _build_ui(self) -> None:
        shell = Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=16, pady=16)

        left = Frame(shell, bg=PANEL, width=320, highlightbackground=PANEL, highlightthickness=0)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        center = Frame(shell, bg=BG)
        center.pack(side="left", fill="both", expand=True, padx=12)

        right = Frame(shell, bg=PANEL, width=380, highlightbackground=PANEL, highlightthickness=0)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        self._build_left_panel(left)
        self._build_center_panel(center)
        self._build_right_panel(right)

    def _build_left_panel(self, parent: Frame) -> None:
        Label(parent, text="Operations", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=18, pady=(18, 4)
        )
        self.operation_list = Listbox(
            parent,
            activestyle="none",
            bg=CANVAS_BG,
            fg=TEXT,
            selectbackground=ACCENT_SOFT,
            selectforeground=TEXT,
            highlightthickness=0,
            relief="flat",
            borderwidth=0,
            height=10,
            font=("Segoe UI", 10),
        )
        for kind in self.operation_kinds:
            self.operation_list.insert("end", EFFECT_LABELS[kind])
        self.operation_list.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Button(parent, text="Add To Stack", style="Accent.TButton", command=self.add_selected_operation).pack(
            fill="x", padx=18
        )

        Label(parent, text="Stack", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=18, pady=(22, 4)
        )
        stack_frame = Frame(parent, bg=CANVAS_BG)
        stack_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.stack_canvas = Canvas(
            stack_frame,
            bg=CANVAS_BG,
            highlightthickness=0,
            relief="flat",
            borderwidth=0,
        )
        self.stack_rows = Frame(self.stack_canvas, bg=CANVAS_BG)
        self.stack_window = self.stack_canvas.create_window((0, 0), window=self.stack_rows, anchor="nw")
        stack_scroll = Scrollbar(stack_frame, orient="vertical", command=self.stack_canvas.yview)
        self.stack_canvas.configure(yscrollcommand=stack_scroll.set)
        self.stack_canvas.pack(side="left", fill="both", expand=True)
        stack_scroll.pack(side="right", fill="y")
        self.stack_rows.bind("<Configure>", self.sync_stack_scroll_region)
        self.stack_canvas.bind("<Configure>", self.sync_stack_width)
        self.stack_canvas.bind("<MouseWheel>", self.scroll_stack)
        self.refresh_stack_list()

    def _build_center_panel(self, parent: Frame) -> None:
        toolbar = Frame(parent, bg=PANEL, highlightthickness=0)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text="Open Image", style="Accent.TButton", command=self.open_image).pack(side="left")
        ttk.Button(toolbar, text="Save Stack Result", command=self.save_result).pack(side="left", padx=(10, 0))
        ttk.Checkbutton(toolbar, text="Sharp Display", variable=self.sharp_preview_var, command=self.schedule_render).pack(
            side="right", padx=(12, 14)
        )
        Label(toolbar, textvariable=self.image_info_var, bg=PANEL, fg=MUTED).pack(side="left", padx=(14, 0))

        self.image_tabs = ttk.Notebook(parent)
        self.image_tabs.pack(fill="both", expand=True)

        original_tab = Frame(self.image_tabs, bg=PANEL)
        preview_tab = Frame(self.image_tabs, bg=PANEL)
        stats_tab = Frame(self.image_tabs, bg=PANEL)
        self.image_tabs.add(original_tab, text="Original")
        self.image_tabs.add(preview_tab, text="Preview")
        self.image_tabs.add(stats_tab, text="Stats")

        self.original_canvas = Canvas(original_tab, bg=CANVAS_BG, bd=0, highlightthickness=0)
        self.preview_canvas = Canvas(preview_tab, bg=CANVAS_BG, bd=0, highlightthickness=0)
        self.original_canvas.pack(fill="both", expand=True, padx=0, pady=10)
        self.preview_canvas.pack(fill="both", expand=True, padx=0, pady=10)

        stats_split = Frame(stats_tab, bg=PANEL)
        stats_split.pack(fill="both", expand=True, padx=0, pady=10)
        self.hist_canvas = Canvas(stats_split, bg=CANVAS_BG, bd=0, highlightthickness=0)
        self.hist_canvas.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.stats_text = Text(
            stats_split,
            width=36,
            bg=CANVAS_BG,
            fg=TEXT,
            relief="flat",
            highlightthickness=0,
            font=("Consolas", 10),
        )
        self.stats_text.pack(side="left", fill="y")
        self.stats_text.insert("end", "Open an image to view stats.")
        self.stats_text.configure(state="disabled")

        self._draw_placeholder(self.original_canvas, "Original")
        self._draw_placeholder(self.preview_canvas, "Preview")

    def _build_right_panel(self, parent: Frame) -> None:
        Label(parent, text="Parameters", bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=18, pady=(18, 4)
        )
        self.params_frame = Frame(parent, bg=PANEL)
        self.params_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.busy_bar = ttk.Progressbar(parent, mode="indeterminate")
        self.busy_bar.pack(fill="x", padx=18, pady=(0, 8))
        Label(parent, textvariable=self.status_var, bg=PANEL, fg=MUTED, wraplength=320, justify="left").pack(
            anchor="w", padx=18, pady=(0, 18)
        )
        self.render_parameter_panel()

    def _bind_events(self) -> None:
        self.operation_list.bind("<Double-Button-1>", lambda _event: self.add_selected_operation())
        self.palette_search_var.trace_add("write", lambda *_: self.debounce_palette_search())
        self.root.bind("<Configure>", lambda _event: self.schedule_render())

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.palette_loading = False
                self.set_idle(str(payload))
            elif kind == "palettes":
                self.receive_palettes(payload)
            elif kind == "palette_search":
                self.receive_palette_search(payload)
            elif kind == "preview":
                self.receive_preview(payload)
            elif kind == "stats":
                self.receive_stats(payload)
        self.root.after(60, self._poll_events)

    def run_background(self, kind: str, func, *args, **kwargs) -> None:
        def worker() -> None:
            try:
                self.events.put((kind, func(*args, **kwargs)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def add_selected_operation(self) -> None:
        selection = self.operation_list.curselection()
        if not selection:
            self.operation_list.selection_set(0)
            selection = (0,)
        kind = self.operation_kinds[selection[0]]
        step = make_effect(kind)
        if kind == "lospec" and self.current_palette:
            step.params["colors"] = list(self.current_palette.colors)
            step.params["palette_title"] = self.current_palette.title
            step.params["palette_slug"] = self.current_palette.slug
        self.effect_steps.append(step)
        self.flash_widget(self.stack_canvas)
        self.status_var.set(f"Added {step.label}")
        self.selected_step_index = len(self.effect_steps) - 1
        self.refresh_stack_list()
        self.render_parameter_panel()
        self.schedule_stack_preview()

    def clear_preview_cache(self) -> None:
        with self.preview_cache_lock:
            self.preview_cache.clear()
            self.preview_cache_bytes = 0
        self.preview_source_cache_key = None
        self.preview_source_cache = None

    def cache_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(
                (str(key), self.cache_value(item))
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            )
        if isinstance(value, (list, tuple)):
            return tuple(self.cache_value(item) for item in value)
        if isinstance(value, set):
            return tuple(sorted((self.cache_value(item) for item in value), key=repr))
        return value

    def step_cache_key(self, step: EffectStep) -> tuple[Any, ...]:
        return (step.kind, self.cache_value(step.params))

    def cached_preview_image(self, key: tuple[Any, ...]) -> Image.Image | None:
        with self.preview_cache_lock:
            entry = self.preview_cache.get(key)
            if entry is None:
                return None
            self.preview_cache.move_to_end(key)
            image, _size = entry
            return image.copy()

    def store_preview_image(self, key: tuple[Any, ...], image: Image.Image) -> None:
        with self.preview_cache_lock:
            old_entry = self.preview_cache.pop(key, None)
            if old_entry is not None:
                self.preview_cache_bytes -= old_entry[1]
            cached = image.copy()
            size = self.image_cache_size(cached)
            self.preview_cache[key] = (cached, size)
            self.preview_cache_bytes += size
            self.preview_cache.move_to_end(key)
            while len(self.preview_cache) > self.preview_cache_limit or (
                self.preview_cache_bytes > self.preview_cache_max_bytes and len(self.preview_cache) > 1
            ):
                _old_key, (_old_image, old_size) = self.preview_cache.popitem(last=False)
                self.preview_cache_bytes -= old_size

    def image_cache_size(self, image: Image.Image) -> int:
        return image.width * image.height * max(1, len(image.getbands()))

    def apply_effect_stack_cached(
        self,
        image: Image.Image,
        steps: list[EffectStep],
        source_version: int,
        *,
        source_key: tuple[Any, ...] | None = None,
    ) -> tuple[Image.Image, int, int]:
        result = image.convert("RGBA")
        state_key = source_key or ("source", source_version, image.size)
        hits = 0
        misses = 0

        for step in steps:
            if not step.enabled:
                continue
            output_key = ("step", state_key, self.step_cache_key(step))
            cached = self.cached_preview_image(output_key)
            if cached is not None:
                result = cached
                hits += 1
            else:
                result = apply_effect(result, step)
                self.store_preview_image(output_key, result)
                misses += 1
            state_key = output_key

        return result, hits, misses

    def sync_stack_scroll_region(self, _event=None) -> None:
        self.stack_canvas.configure(scrollregion=self.stack_canvas.bbox("all"))

    def sync_stack_width(self, event) -> None:
        self.stack_canvas.itemconfigure(self.stack_window, width=max(1, event.width - 4))

    def scroll_stack(self, event) -> None:
        self.stack_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def refresh_stack_list(self) -> None:
        for child in self.stack_rows.winfo_children():
            child.destroy()
        self.stack_row_widgets.clear()

        if self.selected_step_index is not None and self.selected_step_index >= len(self.effect_steps):
            self.selected_step_index = len(self.effect_steps) - 1 if self.effect_steps else None

        if not self.effect_steps:
            empty = Label(
                self.stack_rows,
                text="No effects in stack",
                bg=CANVAS_BG,
                fg=MUTED,
                font=("Segoe UI", 10),
            )
            empty.pack(fill="x", padx=10, pady=14)
            self.sync_stack_scroll_region()
            return

        for index, step in enumerate(self.effect_steps):
            self.create_stack_row(index, step)
        self.sync_stack_scroll_region()

    def create_stack_row(self, index: int, step: EffectStep) -> None:
        selected = index == self.selected_step_index
        row_bg = ACCENT_SOFT if selected else ("#ffffff" if step.enabled else "#f6f8fb")
        row_border = row_bg if not selected else "#c7d8ff"
        text_color = TEXT if step.enabled else MUTED
        row = Frame(self.stack_rows, bg=row_bg, highlightbackground=row_border, highlightthickness=1)
        row.pack(fill="x", padx=0, pady=(0, 8))
        self.stack_row_widgets.append(row)

        top = Frame(row, bg=row_bg)
        top.pack(fill="x", padx=10, pady=(9, 4))
        index_label = Label(
            top,
            text=f"{index + 1:02d}",
            bg=row_bg,
            fg=ACCENT if selected else MUTED,
            width=3,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        )
        index_label.pack(side="left")
        title = Label(
            top,
            text=step.label,
            bg=row_bg,
            fg=text_color,
            anchor="w",
            justify="left",
            wraplength=165,
            font=("Segoe UI", 10, "bold" if selected else "normal"),
        )
        title.pack(side="left", fill="x", expand=True, padx=(6, 8))
        ttk.Button(
            top,
            text="Delete",
            width=7,
            style="Danger.TButton",
            command=lambda i=index: self.delete_step(i),
        ).pack(side="right")

        bottom = Frame(row, bg=row_bg)
        bottom.pack(fill="x", padx=10, pady=(0, 9))
        state = Label(
            bottom,
            text="Enabled" if step.enabled else "Disabled",
            bg=row_bg,
            fg="#166534" if step.enabled else MUTED,
            anchor="w",
            font=("Segoe UI", 9),
        )
        state.pack(side="left", fill="x", expand=True)
        ttk.Button(
            bottom,
            text="Up",
            width=4,
            style="Stack.TButton",
            state="disabled" if index == 0 else "normal",
            command=lambda i=index: self.move_step(i, -1),
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            bottom,
            text="Down",
            width=5,
            style="Stack.TButton",
            state="disabled" if index == len(self.effect_steps) - 1 else "normal",
            command=lambda i=index: self.move_step(i, 1),
        ).pack(side="left", padx=(4, 0))
        ttk.Button(
            bottom,
            text="On" if step.enabled else "Off",
            width=4,
            style="On.TButton" if step.enabled else "Off.TButton",
            command=lambda i=index: self.toggle_step(i),
        ).pack(side="left", padx=(4, 0))

        for widget in (row, top, bottom, index_label, title, state):
            widget.bind("<Button-1>", lambda event, i=index: self.start_stack_drag(event, i))
            widget.bind("<B1-Motion>", self.drag_stack)
            widget.bind("<ButtonRelease-1>", lambda _event: self.finish_stack_drag())
            widget.bind("<MouseWheel>", self.scroll_stack)

    def select_stack_step(self, index: int, *, refresh: bool = True) -> None:
        if not (0 <= index < len(self.effect_steps)):
            return
        if self.selected_step_index == index:
            return
        self.selected_step_index = index
        if refresh:
            self.refresh_stack_list()
        self.render_parameter_panel()

    def selected_step(self) -> EffectStep | None:
        if self.selected_step_index is None:
            return None
        if 0 <= self.selected_step_index < len(self.effect_steps):
            return self.effect_steps[self.selected_step_index]
        return None

    def move_selected_step(self, direction: int) -> None:
        if self.selected_step_index is None:
            return
        self.move_step(self.selected_step_index, direction)

    def move_step(self, index: int, direction: int) -> None:
        new_index = index + direction
        if not (0 <= new_index < len(self.effect_steps)):
            return
        self.effect_steps[index], self.effect_steps[new_index] = self.effect_steps[new_index], self.effect_steps[index]
        self.selected_step_index = new_index
        self.refresh_stack_list()
        self.flash_widget(self.stack_canvas)
        self.render_parameter_panel()
        self.schedule_stack_preview()

    def delete_selected_step(self) -> None:
        if self.selected_step_index is None:
            return
        self.delete_step(self.selected_step_index)

    def delete_step(self, index: int) -> None:
        if not (0 <= index < len(self.effect_steps)):
            return
        label = self.effect_steps[index].label
        del self.effect_steps[index]
        if not self.effect_steps:
            self.selected_step_index = None
        elif self.selected_step_index is None:
            self.selected_step_index = min(index, len(self.effect_steps) - 1)
        elif self.selected_step_index > index:
            self.selected_step_index -= 1
        else:
            self.selected_step_index = min(self.selected_step_index, len(self.effect_steps) - 1)
        self.status_var.set(f"Deleted {label}")
        self.refresh_stack_list()
        self.render_parameter_panel()
        self.schedule_stack_preview()

    def toggle_step(self, index: int) -> None:
        if not (0 <= index < len(self.effect_steps)):
            return
        self.selected_step_index = index
        step = self.effect_steps[index]
        step.enabled = not step.enabled
        self.status_var.set("Step enabled" if step.enabled else "Step disabled")
        self.refresh_stack_list()
        self.render_parameter_panel()
        self.schedule_stack_preview()

    def start_stack_drag(self, _event, index: int) -> None:
        self.drag_index = index
        self.select_stack_step(index, refresh=False)

    def drag_stack(self, event) -> None:
        if self.drag_index is None or not self.effect_steps:
            return
        target = self.stack_drag_target(event.y_root)
        if target is None:
            return
        if target == self.drag_index or not (0 <= target < len(self.effect_steps)):
            return
        step = self.effect_steps.pop(self.drag_index)
        self.effect_steps.insert(target, step)
        self.drag_index = target
        self.selected_step_index = target
        self.refresh_stack_list()
        self.flash_widget(self.stack_canvas)
        self.schedule_stack_preview()

    def stack_drag_target(self, y_root: int) -> int | None:
        for index, row in enumerate(self.stack_row_widgets):
            top = row.winfo_rooty()
            bottom = top + row.winfo_height()
            if top <= y_root <= bottom:
                return index
        return None

    def finish_stack_drag(self) -> None:
        self.drag_index = None
        self.refresh_stack_list()

    def render_parameter_panel(self) -> None:
        self.palette_list = None
        for child in self.params_frame.winfo_children():
            child.destroy()
        self.param_vars.clear()
        step = self.selected_step()
        if not step:
            Label(self.params_frame, text="Select a stack step.", bg=PANEL, fg=MUTED).pack(anchor="w")
            return
        Label(self.params_frame, text=step.label, bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(
            anchor="w", pady=(0, 8)
        )
        self.add_check_param("Enabled", "enabled", step.enabled, lambda value: self.set_step_enabled(value))
        if step.kind == "lospec":
            self.render_lospec_params(step)
        elif step.kind == "gaussian3":
            self.add_slider_param("Iterations", "iterations", 1, 8)
            self.add_slider_param("Strength", "strength", 0, 100)
        elif step.kind == "box_blur":
            self.add_slider_param("Radius", "radius", 0, 20)
            self.add_slider_param("Strength", "strength", 0, 100)
        elif step.kind == "laplace":
            self.add_combo_param("Mode", "mode", ("edges", "add"))
            self.add_slider_param("Strength", "strength", 0, 300)
        elif step.kind == "sobel":
            self.add_check_param("Grayscale", "grayscale", bool(step.params.get("grayscale", True)))
            self.add_slider_param("Strength", "strength", 0, 300)
        elif step.kind in {"erosion", "dilation"}:
            self.add_slider_param("Kernel Size", "size", 3, 15, odd=True)
            self.add_slider_param("Iterations", "iterations", 1, 8)
        elif step.kind in {"opening", "closing"}:
            self.add_slider_param("Kernel Size", "size", 3, 15, odd=True)
            self.add_slider_param("Iterations", "iterations", 1, 8)
        elif step.kind == "morph_gradient":
            self.add_slider_param("Kernel Size", "size", 3, 15, odd=True)
        elif step.kind == "pixelize":
            self.add_combo_param("Algorithm", "algorithm", ("average", "median", "nearest", "posterize", "ordered_dither"))
            self.add_slider_param("Pixel Size", "pixel_size", 2, 64)
            self.add_slider_param("Levels", "levels", 2, 32)
            self.add_slider_param("Strength", "strength", 0, 100)
        elif step.kind == "pixel_perfect":
            self.add_slider_param("Pixel Size", "pixel_size", 1, 32)
            self.add_slider_param("Color Levels", "levels", 2, 32)
            self.add_check_param("Snap Colors", "snap_colors", bool(step.params.get("snap_colors", True)))
        elif step.kind == "unsharp":
            self.add_slider_param("Radius", "radius", 0, 12)
            self.add_slider_param("Percent", "percent", 0, 500)
            self.add_slider_param("Threshold", "threshold", 0, 64)
        elif step.kind in {"sharpen", "emboss", "edge_enhance", "invert"}:
            self.add_slider_param("Strength", "strength", 0, 300 if step.kind == "sharpen" else 100)
        elif step.kind == "median":
            self.add_slider_param("Kernel Size", "size", 3, 15, odd=True)
        elif step.kind == "threshold":
            self.add_slider_param("Threshold", "threshold", 0, 255)
            self.add_check_param("Invert", "invert", bool(step.params.get("invert", False)))
        elif step.kind == "posterize":
            self.add_slider_param("Bits", "bits", 1, 8)
        elif step.kind == "color_adjust":
            self.add_slider_param("Brightness", "brightness", 0, 300)
            self.add_slider_param("Contrast", "contrast", 0, 300)
            self.add_slider_param("Saturation", "saturation", 0, 300)
        elif step.kind == "contrast":
            self.add_slider_param("Amount", "amount", 0, 300)
        elif step.kind == "gamma":
            self.add_slider_param("Gamma x100", "gamma", 5, 500)
        elif step.kind == "dog":
            self.add_slider_param("Small Radius", "small_radius", 0, 12, as_float=True)
            self.add_slider_param("Large Radius", "large_radius", 1, 24, as_float=True)
            self.add_slider_param("Strength", "strength", 0, 300)

    def render_lospec_params(self, step: EffectStep) -> None:
        self.add_check_param("Preserve Alpha", "preserve_alpha", bool(step.params.get("preserve_alpha", True)))
        current = step.params.get("palette_title") or "No palette selected"
        Label(self.params_frame, text=current, bg=PANEL, fg=MUTED, wraplength=320).pack(anchor="w", pady=(4, 8))
        row = Frame(self.params_frame, bg=PANEL)
        row.pack(fill="x", pady=(0, 8))
        ttk.Entry(row, textvariable=self.palette_search_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Clear", command=self.clear_palette_search).pack(side="left", padx=(8, 0))

        sort_row = Frame(self.params_frame, bg=PANEL)
        sort_row.pack(fill="x", pady=(0, 8))
        sort_combo = ttk.Combobox(
            sort_row,
            textvariable=self.palette_sort_var,
            state="readonly",
            values=("default", "downloads", "newest", "alphabetical"),
            width=14,
        )
        sort_combo.pack(side="left", fill="x", expand=True)
        sort_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_palettes(reset=True))
        ttk.Button(sort_row, text="Refresh", command=lambda: self.load_palettes(reset=True, refresh=True)).pack(
            side="left", padx=(8, 0)
        )

        list_frame = Frame(self.params_frame, bg=PANEL)
        list_frame.pack(fill="both", expand=True, pady=(0, 8))
        self.palette_list = Listbox(
            list_frame,
            activestyle="none",
            bg="#ffffff",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            relief="flat",
            borderwidth=0,
            height=10,
            font=("Segoe UI", 9),
        )
        palette_scrollbar = Scrollbar(list_frame, orient="vertical", command=self.palette_yview)
        self.palette_list.configure(yscrollcommand=lambda first, last: self.palette_yscroll(palette_scrollbar, first, last))
        self.palette_list.pack(side="left", fill="both", expand=True)
        palette_scrollbar.pack(side="right", fill="y")
        self.palette_list.bind("<<ListboxSelect>>", self.on_palette_select)
        self.palette_list.bind("<MouseWheel>", lambda _event: self.root.after(20, self.maybe_autoload_palettes))
        self.populate_palette_listbox()
        ttk.Button(self.params_frame, text="Load More Palettes", command=self.load_more_palettes).pack(fill="x")

    def add_slider_param(
        self,
        label: str,
        key: str,
        start: int,
        end: int,
        *,
        odd: bool = False,
        as_float: bool = False,
    ) -> None:
        step = self.selected_step()
        if not step:
            return
        group = Frame(self.params_frame, bg=PANEL)
        group.pack(fill="x", pady=(8, 0))
        value_var = DoubleVar(value=float(step.params.get(key, start)))
        self.param_vars.append(value_var)
        title_var = StringVar()
        self.param_vars.append(title_var)

        def update_label() -> None:
            if as_float:
                title_var.set(f"{label}: {value_var.get():.1f}")
                return
            value = int(round(value_var.get()))
            if odd and value % 2 == 0:
                value += 1
            title_var.set(f"{label}: {value}")

        def changed(_value=None) -> None:
            if as_float:
                step.params[key] = float(value_var.get())
                update_label()
                self.status_var.set(f"Updated {label}")
                self.schedule_stack_preview()
                return
            value = int(round(value_var.get()))
            if odd and value % 2 == 0:
                value += 1
            step.params[key] = value
            update_label()
            self.status_var.set(f"Updated {label}")
            self.schedule_stack_preview()

        Label(group, textvariable=title_var, bg=PANEL, fg=MUTED).pack(anchor="w")
        ttk.Scale(group, from_=start, to=end, variable=value_var, command=changed).pack(fill="x")
        update_label()

    def add_combo_param(self, label: str, key: str, values: tuple[str, ...]) -> None:
        step = self.selected_step()
        if not step:
            return
        group = Frame(self.params_frame, bg=PANEL)
        group.pack(fill="x", pady=(8, 0))
        Label(group, text=label, bg=PANEL, fg=MUTED).pack(anchor="w")
        var = StringVar(value=str(step.params.get(key, values[0])))
        self.param_vars.append(var)
        combo = ttk.Combobox(group, textvariable=var, values=values, state="readonly")
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda _event: self.update_param(key, var.get()))

    def add_check_param(self, label: str, key: str, value: bool, command=None) -> None:
        var = BooleanVar(value=value)
        self.param_vars.append(var)
        callback = command or (lambda new_value: self.update_param(key, bool(new_value)))
        ttk.Checkbutton(self.params_frame, text=label, variable=var, command=lambda: callback(var.get())).pack(
            anchor="w", pady=(4, 0)
        )

    def update_param(self, key: str, value) -> None:
        step = self.selected_step()
        if not step:
            return
        step.params[key] = value
        self.status_var.set(f"Updated {key}")
        self.schedule_stack_preview()

    def set_step_enabled(self, value: bool) -> None:
        step = self.selected_step()
        if not step:
            return
        step.enabled = value
        self.status_var.set("Step enabled" if value else "Step disabled")
        self.refresh_stack_list()
        self.render_parameter_panel()
        self.schedule_stack_preview()

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            image = Image.open(path)
            image.load()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        self.image_path = Path(path)
        self.source_image = image.convert("RGBA")
        self.source_version += 1
        self.clear_preview_cache()
        self.clear_display_cache()
        self.preview_image = self.preview_source_image()
        self.result_image = None
        self.image_info_var.set(f"{self.image_path.name}  |  {self.source_image.width} x {self.source_image.height}")
        self.schedule_render()
        self.schedule_stack_preview()
        self.schedule_stats()

    def schedule_stack_preview(self) -> None:
        if self.source_image:
            self.result_image = None
        if self.stack_after_id:
            self.root.after_cancel(self.stack_after_id)
        self.stack_after_id = self.root.after(180, self.start_stack_preview)

    def start_stack_preview(self) -> None:
        if not self.source_image:
            return
        self.stack_after_id = None
        if self.preview_rendering:
            self.preview_token += 1
            self.preview_pending = True
            return
        self.preview_token += 1
        token = self.preview_token
        source = self.preview_source_image()
        source_version = self.source_version
        source_key = ("preview-source", source_version, source.size, PREVIEW_MAX_EDGE)
        steps = [step.copy() for step in self.effect_steps]
        if not any(step.enabled for step in steps):
            self.preview_image = source
            self.set_idle("Preview updated")
            self.schedule_render()
            return
        self.preview_rendering = True
        self.preview_pending = False
        self.set_busy("Rendering stack preview...")

        def build_preview() -> tuple[int, Image.Image, int, int]:
            image, hits, misses = self.apply_effect_stack_cached(source, steps, source_version, source_key=source_key)
            return token, image, hits, misses

        self.run_background("preview", build_preview)

    def receive_preview(self, payload: object) -> None:
        token, image, hits, _misses = payload  # type: ignore[misc]
        self.preview_rendering = False
        if token != self.preview_token:
            if self.preview_pending:
                self.preview_pending = False
                self.start_stack_preview()
            return
        self.preview_image = image
        suffix = f" ({hits} cached)" if hits else ""
        self.set_idle(f"Preview updated{suffix}")
        self.schedule_render()
        if self.preview_pending:
            self.preview_pending = False
            self.start_stack_preview()

    def preview_source_image(self) -> Image.Image:
        if not self.source_image:
            raise ValueError("No source image")
        source = self.source_image
        cache_key = (self.source_version, source.size, PREVIEW_MAX_EDGE)
        if self.preview_source_cache_key == cache_key and self.preview_source_cache is not None:
            return self.preview_source_cache.copy()
        if max(source.size) <= PREVIEW_MAX_EDGE:
            preview = source.copy()
        else:
            preview = source.copy()
            preview.thumbnail((PREVIEW_MAX_EDGE, PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
        self.preview_source_cache_key = cache_key
        self.preview_source_cache = preview
        return preview.copy()

    def save_result(self) -> None:
        if not self.source_image:
            messagebox.showinfo("No image", "Open an image first.")
            return
        default = self.output_name()
        path = filedialog.asksaveasfilename(
            title="Save stack result",
            defaultextension=".png",
            initialfile=default,
            filetypes=[("PNG", "*.png"), ("WebP", "*.webp"), ("JPEG", "*.jpg"), ("All files", "*.*")],
        )
        if not path:
            return
        if self.result_image is None:
            self.set_busy("Rendering full-size result...")
            result, _hits, _misses = self.apply_effect_stack_cached(
                self.source_image,
                [step.copy() for step in self.effect_steps],
                self.source_version,
                source_key=("full-source", self.source_version, self.source_image.size),
            )
            self.result_image = result
        else:
            result = self.result_image
        if Path(path).suffix.lower() in {".jpg", ".jpeg"}:
            result = result.convert("RGB")
        result.save(path)
        self.set_idle(f"Saved {Path(path).name}")

    def output_name(self) -> str:
        stem = self.image_path.stem if self.image_path else "image"
        return f"{stem}-stack.png"

    def schedule_render(self) -> None:
        if self.resize_after_id:
            self.root.after_cancel(self.resize_after_id)
        self.resize_after_id = self.root.after(180, self.safe_render_images)

    def safe_render_images(self) -> None:
        try:
            self.resize_after_id = None
            self.render_images()
        except TclError:
            pass

    def render_images(self) -> None:
        self.render_image_canvas(self.original_canvas, self.source_image, "Original", original=True)
        self.render_image_canvas(self.preview_canvas, self.preview_image, "Preview", original=False)

    def render_image_canvas(self, canvas: Canvas, image: Image.Image | None, label: str, *, original: bool) -> None:
        if image is None:
            self.clear_canvas_cache(original)
            self._draw_placeholder(canvas, label)
            return
        width = max(120, canvas.winfo_width() - 28)
        height = max(120, canvas.winfo_height() - 48)
        resample = Image.Resampling.NEAREST if self.sharp_preview_var.get() else Image.Resampling.LANCZOS
        photo_key = (id(image), image.size, width, height, self.sharp_preview_var.get())
        old_key = self.original_photo_key if original else self.preview_photo_key
        if photo_key != old_key:
            display_size = display_image_size(image.size, (width, height))
            fitted = image.copy() if display_size == image.size else image.resize(display_size, resample)
            photo = ImageTk.PhotoImage(fitted)
            fitted_width, fitted_height = fitted.width, fitted.height
            if original:
                self.original_photo = photo
                self.original_photo_key = photo_key
            else:
                self.preview_photo = photo
                self.preview_photo_key = photo_key
        else:
            photo = self.original_photo if original else self.preview_photo
            if photo is None:
                return
            fitted_width, fitted_height = photo.width(), photo.height()
        x = max(14, (canvas.winfo_width() - fitted_width) // 2)
        y = max(34, (canvas.winfo_height() - fitted_height) // 2 + 12)
        items = self.original_canvas_items if original else self.preview_canvas_items
        if items is None:
            canvas.delete("all")
            text_item = canvas.create_text(16, 16, anchor="w", fill=MUTED, font=("Segoe UI", 10, "bold"), text=label)
            image_item = canvas.create_image(x, y, anchor="nw", image=photo)
            if original:
                self.original_canvas_items = (text_item, image_item)
            else:
                self.preview_canvas_items = (text_item, image_item)
        else:
            text_item, image_item = items
            canvas.coords(text_item, 16, 16)
            canvas.itemconfigure(text_item, text=label)
            canvas.coords(image_item, x, y)
            canvas.itemconfigure(image_item, image=photo)

    def clear_display_cache(self) -> None:
        self.original_photo_key = None
        self.preview_photo_key = None
        self.original_canvas_items = None
        self.preview_canvas_items = None

    def clear_canvas_cache(self, original: bool) -> None:
        if original:
            self.original_photo_key = None
            self.original_canvas_items = None
        else:
            self.preview_photo_key = None
            self.preview_canvas_items = None

    def _draw_placeholder(self, canvas: Canvas, label: str) -> None:
        canvas.delete("all")
        canvas.create_text(16, 16, anchor="w", fill=MUTED, font=("Segoe UI", 10, "bold"), text=label)
        canvas.create_text(
            max(80, canvas.winfo_width() // 2),
            max(80, canvas.winfo_height() // 2),
            fill="#9aa4b2",
            font=("Segoe UI", 12),
            text="Open an image first",
        )

    def schedule_stats(self) -> None:
        if not self.source_image:
            return
        self.stats_token += 1
        token = self.stats_token
        source = self.source_image.copy()

        def build_stats() -> tuple[int, dict, dict]:
            return token, image_statistics(source), histogram_rgb(source)

        self.run_background("stats", build_stats)

    def receive_stats(self, payload: object) -> None:
        token, stats, hist = payload  # type: ignore[misc]
        if token != self.stats_token:
            return
        self.render_stats(stats)
        self.render_histogram(hist)

    def render_stats(self, stats: dict) -> None:
        lines = [
            f"Size: {stats['size'][0]} x {stats['size'][1]}",
            f"Mode: {stats['mode']}",
            f"Sample pixels: {stats['sample_pixels']}",
            f"Mean RGB: {stats['mean_rgb']}",
            f"Median RGB: {stats['median_rgb']}",
            f"Std RGB: {stats['std_rgb']}",
            f"Luma min/max: {stats['min_luma']:.1f} / {stats['max_luma']:.1f}",
            "",
            "Dominant colors:",
        ]
        for color, count in stats["dominant_colors"]:
            lines.append(f"#{color}  {count}")
        self.stats_text.configure(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("end", "\n".join(lines))
        self.stats_text.configure(state="disabled")

    def render_histogram(self, hist: dict[str, list[int]]) -> None:
        canvas = self.hist_canvas
        canvas.delete("all")
        width = max(300, canvas.winfo_width())
        height = max(180, canvas.winfo_height())
        canvas.create_text(16, 16, anchor="w", fill=MUTED, font=("Segoe UI", 10, "bold"), text="RGB Histogram")
        graph_x, graph_y = 16, 42
        graph_w, graph_h = width - 32, height - 60
        max_value = max(max(hist["r"]), max(hist["g"]), max(hist["b"]), 1)
        for channel, color in {"r": "#ef4444", "g": "#22c55e", "b": "#3b82f6"}.items():
            points: list[float] = []
            for index, value in enumerate(hist[channel]):
                points.extend([graph_x + graph_w * index / 255, graph_y + graph_h - graph_h * value / max_value])
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=1.4)
        canvas.create_rectangle(graph_x, graph_y, graph_x + graph_w, graph_y + graph_h, outline=BORDER)

    def load_palettes(self, *, reset: bool, refresh: bool = False) -> None:
        if reset:
            self.palette_page = -1
            self.palette_total = 0
            self.palettes.clear()
            self.populate_palette_listbox()
        self.load_more_palettes(refresh=refresh)

    def load_more_palettes(self, refresh: bool = False) -> None:
        if self.palette_mode != "list" or self.palette_loading:
            return
        if self.palette_total and len(self.palettes) >= self.palette_total:
            return
        page = self.palette_page + 1
        sort = self.palette_sort_var.get()
        self.palette_loading = True
        self.set_busy("Loading palettes...")

        def load_page() -> tuple[int, list[Palette], int]:
            palettes, total = self.client.list_palettes(page=page, sorting_type=sort, refresh=refresh)
            return page, palettes, total

        self.run_background("palettes", load_page)

    def receive_palettes(self, payload: object) -> None:
        page, palettes, total = payload  # type: ignore[misc]
        self.palette_loading = False
        self.palette_page = max(self.palette_page, page)
        self.palette_total = total
        previous_count = len(self.palettes)
        self.palettes.extend(palettes)
        if previous_count == 0 or page == 0:
            self.populate_palette_listbox()
        else:
            self.append_palette_rows(palettes)
        self.set_idle(f"Palettes {len(self.palettes)} / {self.palette_total}")
        if len(self.palettes) < 40 and len(self.palettes) < self.palette_total:
            self.load_more_palettes()

    def debounce_palette_search(self) -> None:
        if self.palette_search_after_id:
            self.root.after_cancel(self.palette_search_after_id)
        self.palette_search_after_id = self.root.after(350, self.perform_palette_search)

    def perform_palette_search(self) -> None:
        query = self.palette_search_var.get().strip()
        self.palette_search_token += 1
        token = self.palette_search_token
        if not query:
            self.palette_mode = "list"
            self.load_palettes(reset=True)
            return
        self.palette_mode = "search"
        self.set_busy("Searching palettes...")

        def search() -> tuple[int, list[Palette]]:
            return token, self.client.search_palettes(query)

        self.run_background("palette_search", search)

    def receive_palette_search(self, payload: object) -> None:
        token, palettes = payload  # type: ignore[misc]
        if token != self.palette_search_token:
            return
        self.palettes = list(palettes)
        self.populate_palette_listbox()
        self.set_idle(f"Found {len(self.palettes)} palettes")

    def clear_palette_search(self) -> None:
        self.palette_search_var.set("")
        self.palette_mode = "list"
        self.load_palettes(reset=True)

    def populate_palette_listbox(self) -> None:
        if not self.palette_list:
            return
        try:
            self.palette_list.delete(0, "end")
        except TclError:
            return
        for palette in self.palettes:
            self.palette_list.insert("end", f"{palette.title} | {palette.color_count}")

    def append_palette_rows(self, palettes: list[Palette]) -> None:
        if not self.palette_list:
            return
        try:
            first, _last = self.palette_list.yview()
            for palette in palettes:
                self.palette_list.insert("end", f"{palette.title} | {palette.color_count}")
            self.palette_list.yview_moveto(first)
        except TclError:
            return

    def on_palette_select(self, _event=None) -> None:
        if not self.palette_list:
            return
        selection = self.palette_list.curselection()
        if not selection:
            return
        index = selection[0]
        if not (0 <= index < len(self.palettes)):
            return
        self.current_palette = self.palettes[index]
        step = self.selected_step()
        if step and step.kind == "lospec":
            step.params["colors"] = list(self.current_palette.colors)
            step.params["palette_title"] = self.current_palette.title
            step.params["palette_slug"] = self.current_palette.slug
            self.refresh_stack_list()
            self.flash_widget(self.palette_list)
            self.status_var.set(f"Selected palette: {self.current_palette.title}")
            self.schedule_stack_preview()

    def palette_yview(self, *args) -> None:
        if self.palette_list:
            self.palette_list.yview(*args)
        self.root.after(20, self.maybe_autoload_palettes)

    def palette_yscroll(self, scrollbar: Scrollbar, first: str, last: str) -> None:
        scrollbar.set(first, last)
        if float(last) > 0.86:
            self.root.after(20, self.maybe_autoload_palettes)

    def maybe_autoload_palettes(self) -> None:
        if self.palette_mode == "list" and self.palette_list and self.palette_list.yview()[1] > 0.86:
            self.load_more_palettes()

    def export_palette_png(self) -> None:
        palette = self.current_palette
        if not palette:
            return
        path = filedialog.asksaveasfilename(
            title="Export palette PNG",
            defaultextension=".png",
            initialfile=f"{palette.slug}.png",
            filetypes=[("PNG", "*.png")],
        )
        if path:
            save_palette_png(palette.colors, path)
            self.set_idle(f"Exported {Path(path).name}")

    def export_palette_gpl(self) -> None:
        palette = self.current_palette
        if not palette:
            return
        path = filedialog.asksaveasfilename(
            title="Export GIMP GPL",
            defaultextension=".gpl",
            initialfile=f"{palette.slug}.gpl",
            filetypes=[("GIMP Palette", "*.gpl"), ("All files", "*.*")],
        )
        if path:
            save_palette_gpl(palette.colors, path, name=palette.title)
            self.set_idle(f"Exported {Path(path).name}")

    def set_busy(self, message: str) -> None:
        self.status_var.set(message)
        try:
            self.busy_bar.start(10)
        except TclError:
            pass

    def set_idle(self, message: str) -> None:
        self.status_var.set(message)
        try:
            self.busy_bar.stop()
        except TclError:
            pass

    def flash_widget(self, widget) -> None:
        try:
            original = widget.cget("bg")
            widget.configure(bg="#f0f7ff")
            self.root.after(140, lambda: widget.configure(bg=original))
        except TclError:
            pass


def main() -> None:
    root = Tk()
    ColorUtilsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
