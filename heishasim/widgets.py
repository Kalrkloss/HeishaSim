from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from .models import DisplayMode, ParameterDefinition, RelayDefinition


class DialControl(tk.Canvas):
    def __init__(self, master, minimum: float, maximum: float, step: float, command, **kwargs):
        super().__init__(master, width=160, height=160, bg="#fbf7ef", highlightthickness=0, **kwargs)
        self.minimum = minimum
        self.maximum = maximum
        self.step = step if step > 0 else 1.0
        self.command = command
        self.value = minimum
        self.sweep_start = -135
        self.sweep_extent = 270
        self.visual_offset = -90
        self.bind("<Button-1>", self._on_pointer)
        self.bind("<B1-Motion>", self._on_pointer)
        self._draw()

    def set(self, value: float) -> None:
        self.value = max(self.minimum, min(self.maximum, value))
        self._draw()

    def _on_pointer(self, event) -> None:
        cx, cy, _, _, _, _ = self._dial_geometry()
        dx = event.x - cx
        dy = event.y - cy
        raw_angle = math.degrees(math.atan2(dy, dx))
        logical_angle = self._normalize_logical_angle(raw_angle - self.visual_offset)
        angle = max(self.sweep_start, min(self.sweep_start + self.sweep_extent, logical_angle))
        ratio = (angle - self.sweep_start) / float(self.sweep_extent)
        new_value = self.minimum + (self.maximum - self.minimum) * ratio
        self.value = new_value
        self._draw()
        self.command(new_value)

    def _normalize_logical_angle(self, logical_angle: float) -> float:
        # Keep angle continuity around sweep center so dragging does not jump at atan2 wrap.
        sweep_center = self.sweep_start + (self.sweep_extent / 2.0)
        candidates = (logical_angle - 360.0, logical_angle, logical_angle + 360.0)
        return min(candidates, key=lambda a: abs(a - sweep_center))

    def _format_scale_value(self, value: float) -> str:
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text

    def _scale_values(self) -> list[float]:
        value_range = max(0.0001, self.maximum - self.minimum)
        max_labels = 7
        multiplier = max(1, int(math.ceil(value_range / (self.step * (max_labels - 1)))))
        major_step = self.step * multiplier

        values = []
        current = self.minimum
        guard = 0
        while current < (self.maximum - (major_step / 2.0)) and guard < 200:
            values.append(round(current, 6))
            current += major_step
            guard += 1

        if not values or abs(values[0] - self.minimum) > 1e-6:
            values.insert(0, self.minimum)
        if abs(values[-1] - self.maximum) > 1e-6:
            values.append(self.maximum)

        return sorted(set(values))

    def _dial_geometry(self):
        raw_width = int(self.winfo_width())
        raw_height = int(self.winfo_height())
        # Before first layout pass Tk can report 1x1; use configured size in that case.
        if raw_width <= 2:
            raw_width = int(self.cget("width") or 160)
        if raw_height <= 2:
            raw_height = int(self.cget("height") or 160)

        width = max(80, raw_width)
        height = max(80, raw_height)
        size = min(width, height)
        cx = width / 2.0
        cy = height / 2.0
        outer_radius = (size / 2.0) - max(8, size * 0.12)
        arc_radius = outer_radius - max(4, size * 0.05)
        needle_radius = arc_radius - max(8, size * 0.11)
        label_radius = outer_radius + max(8, size * 0.09)
        return cx, cy, outer_radius, arc_radius, needle_radius, label_radius

    def _draw(self) -> None:
        self.delete("all")
        cx, cy, outer_radius, arc_radius, needle_radius, label_radius = self._dial_geometry()
        size = max(80, int(outer_radius * 2 + max(16, outer_radius * 0.24)))
        tick_outer = outer_radius
        major_tick_inner = outer_radius - max(10, size * 0.14)
        minor_tick_inner = outer_radius - max(6, size * 0.09)
        arc_width = max(6, int(size * 0.07))
        ring_width = max(1, int(size * 0.015))
        label_font_size = max(8, int(size * 0.055))
        needle_width = max(2, int(size * 0.03))
        hub_radius = max(4, int(size * 0.04))

        self.create_oval(
            cx - outer_radius,
            cy - outer_radius,
            cx + outer_radius,
            cy + outer_radius,
            outline="#244b5a",
            width=ring_width,
            fill="#ffffff",
        )
        arc_start_canvas = -(self.sweep_start + self.visual_offset)
        self.create_arc(
            cx - arc_radius,
            cy - arc_radius,
            cx + arc_radius,
            cy + arc_radius,
            # Convert dial angle space (y-down) to Tk canvas angle space (y-up).
            start=arc_start_canvas,
            extent=-self.sweep_extent,
            style=tk.ARC,
            outline="#d7e4ea",
            width=arc_width,
        )

        # Draw major ticks and labels on real values only.
        scale_values = self._scale_values()
        for scale_value in scale_values:
            ratio_label = (scale_value - self.minimum) / (self.maximum - self.minimum or 1)
            ratio_label = max(0.0, min(1.0, ratio_label))
            logical_angle = self.sweep_start + ratio_label * self.sweep_extent
            display_angle = logical_angle + self.visual_offset
            rad = math.radians(display_angle)

            outer_x = cx + tick_outer * math.cos(rad)
            outer_y = cy + tick_outer * math.sin(rad)
            inner_x = cx + major_tick_inner * math.cos(rad)
            inner_y = cy + major_tick_inner * math.sin(rad)
            self.create_line(inner_x, inner_y, outer_x, outer_y, fill="#7e98a3", width=2)

            self.create_text(
                cx + label_radius * math.cos(rad),
                cy + label_radius * math.sin(rad),
                text=self._format_scale_value(scale_value),
                fill="#4d6570",
                font=("Segoe UI", label_font_size, "bold"),
            )

        ratio = (self.value - self.minimum) / (self.maximum - self.minimum or 1)
        ratio = max(0.0, min(1.0, ratio))
        logical_angle = self.sweep_start + ratio * self.sweep_extent
        display_angle = logical_angle + self.visual_offset
        rad = math.radians(display_angle)
        x = cx + needle_radius * math.cos(rad)
        y = cy + needle_radius * math.sin(rad)

        self.create_line(cx, cy, x, y, fill="#e05a47", width=needle_width)
        self.create_oval(cx - hub_radius, cy - hub_radius, cx + hub_radius, cy + hub_radius, fill="#244b5a", outline="")


class ParameterWidget(tk.Frame):
    def __init__(self, master, definition: ParameterDefinition, value: float, on_change, on_resize=None):
        super().__init__(master, bg="#fbf7ef", bd=1, relief=tk.RIDGE)
        self.definition = definition
        self.on_change = on_change
        self.on_resize = on_resize
        self.mode_var = tk.StringVar(value="number")
        self.value_var = tk.DoubleVar(value=value)
        self.min_width = 220
        self.min_height = 190
        self._resize_state = None
        self.style = ttk.Style(self)
        self.style_prefix = f"Heisha.{self.definition.key}"
        self.button_style = f"{self.style_prefix}.TButton"
        self.entry_style = f"{self.style_prefix}.TEntry"
        self.combo_style = f"{self.style_prefix}.TCombobox"
        self.scale_style = f"{self.style_prefix}.Horizontal.TScale"
        self.bind("<Configure>", self._on_widget_configure)

        self.configure(width=260, height=220)
        self.pack_propagate(False)

        self.header = tk.Frame(self, bg="#244b5a", height=30)
        self.header.pack(fill=tk.X)

        self.title_label = tk.Label(
            self.header,
            text=f"{definition.label} ({definition.unit})",
            bg="#244b5a",
            fg="#f7f5ef",
            font=("Segoe UI", 10, "bold"),
        )
        self.title_label.pack(side=tk.LEFT, padx=8)

        self.mode_combo = ttk.Combobox(
            self.header,
            width=9,
            state="readonly",
            values=("number", "slider", "dial"),
            textvariable=self.mode_var,
            style=self.combo_style,
        )
        self.mode_combo.pack(side=tk.RIGHT, padx=6, pady=3)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_selected)

        self.body = tk.Frame(self, bg="#fbf7ef")
        self.body.pack(fill=tk.BOTH, expand=True)

        self._cursor_zone = None
        self._bind_resize_events()

        self._render_mode()
        self._bind_resize_to_children()

    def set_value(self, value: float) -> None:
        value = max(self.definition.minimum, min(self.definition.maximum, value))
        self.value_var.set(round(value, 2))
        if hasattr(self, "big_value"):
            try:
                self.big_value.configure(text=f"{self.value_var.get():.1f}")
            except tk.TclError:
                pass
        if hasattr(self, "slider"):
            self.slider.set(self.value_var.get())
        if hasattr(self, "dial"):
            self.dial.set(self.value_var.get())

    def get_value(self) -> float:
        return self.value_var.get()

    def set_mode(self, mode: DisplayMode) -> None:
        self.mode_var.set(mode)
        self._render_mode()
        self._bind_resize_to_children()

    def get_mode(self) -> DisplayMode:
        return self.mode_var.get()  # type: ignore[return-value]

    def _adjust(self, direction: int) -> None:
        new_value = self.value_var.get() + (self.definition.step * direction)
        self._apply_new_value(new_value)

    def _submit_entry(self, *_args) -> None:
        try:
            value = float(self.entry_var.get())
        except ValueError:
            self.entry_var.set(f"{self.value_var.get():.2f}")
            return
        self._apply_new_value(value)

    def _apply_new_value(self, value: float) -> None:
        value = max(self.definition.minimum, min(self.definition.maximum, value))
        self.value_var.set(round(value, 2))
        self.entry_var.set(f"{self.value_var.get():.2f}")
        if hasattr(self, "big_value"):
            try:
                self.big_value.configure(text=f"{self.value_var.get():.1f}")
            except tk.TclError:
                pass
        if hasattr(self, "dial"):
            self.dial.set(self.value_var.get())
        self.on_change(self.definition.key, self.value_var.get())

    def _render_mode(self, *_args) -> None:
        for child in self.body.winfo_children():
            child.destroy()

        self.entry_var = tk.StringVar(value=f"{self.value_var.get():.2f}")

        controls = tk.Frame(self.body, bg="#fbf7ef")
        controls.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=8)
        self.controls = controls

        down_btn = ttk.Button(controls, text="-", width=3, command=lambda: self._adjust(-1), style=self.button_style)
        down_btn.pack(side=tk.LEFT)
        self.down_btn = down_btn

        entry = ttk.Entry(controls, textvariable=self.entry_var, width=10, style=self.entry_style)
        entry.pack(side=tk.LEFT, padx=6)
        entry.bind("<Return>", self._submit_entry)
        self.entry = entry

        up_btn = ttk.Button(controls, text="+", width=3, command=lambda: self._adjust(1), style=self.button_style)
        up_btn.pack(side=tk.LEFT)
        self.up_btn = up_btn

        set_btn = ttk.Button(controls, text="Set", command=self._submit_entry, style=self.button_style)
        set_btn.pack(side=tk.LEFT, padx=6)
        self.set_btn = set_btn

        mode = self.mode_var.get()
        if mode == "slider":
            self.slider = ttk.Scale(
                self.body,
                from_=self.definition.minimum,
                to=self.definition.maximum,
                orient=tk.HORIZONTAL,
                command=lambda v: self._apply_new_value(float(v)),
                style=self.scale_style,
            )
            self.slider.set(self.value_var.get())
            self.slider.pack(fill=tk.X, padx=12, pady=16)

            self.big_value = tk.Label(
                self.body,
                text=f"{self.value_var.get():.1f}",
                bg="#fbf7ef",
                fg="#244b5a",
                font=("Segoe UI", 28, "bold"),
            )
            self.big_value.pack(pady=4)
            self._apply_layout_scale()
            return

        if mode == "dial":
            self.dial = DialControl(
                self.body,
                self.definition.minimum,
                self.definition.maximum,
                self.definition.step,
                command=lambda v: self._apply_new_value(float(v)),
            )
            self.dial.set(self.value_var.get())
            self.dial.pack(pady=(6, 2))

            self.big_value = tk.Label(
                self.body,
                text=f"{self.value_var.get():.1f}",
                bg="#fbf7ef",
                fg="#244b5a",
                font=("Segoe UI", 24, "bold"),
            )
            self.big_value.pack(pady=(0, 8))
            self._apply_layout_scale()
            return

        self.big_value = tk.Label(
            self.body,
            text=f"{self.value_var.get():.1f}",
            bg="#fbf7ef",
            fg="#244b5a",
            font=("Segoe UI", 40, "bold"),
        )
        self.big_value.pack(expand=True)
        self._apply_layout_scale()

    def _on_widget_configure(self, _event=None) -> None:
        self._apply_layout_scale()

    def _apply_layout_scale(self) -> None:
        width = max(self.min_width, self.winfo_width() or int(self.cget("width")))
        height = max(self.min_height, self.winfo_height() or int(self.cget("height")))
        scale = min(width / 260.0, height / 220.0)

        header_h = max(28, int(30 * scale))
        title_font = max(9, int(10 * scale))
        combo_chars = max(7, min(14, int(width / 28)))
        pad_x = max(6, int(8 * scale))
        pad_y = max(5, int(8 * scale))
        entry_chars = max(8, min(16, int(width / 24)))
        btn_chars = max(2, min(5, int(width / 85)))
        ttk_font = max(8, int(9 * scale))
        entry_pad = max(2, int(4 * scale))
        button_pad = max(2, int(5 * scale))
        combo_pad = max(2, int(4 * scale))
        slider_thickness = max(12, int(16 * scale))
        slider_trough = max(8, int(10 * scale))

        self.header.configure(height=header_h)
        self.title_label.configure(font=("Segoe UI", title_font, "bold"))
        self.mode_combo.configure(width=combo_chars)

        # Per-widget ttk style scaling to keep controls proportionate to widget size.
        self.style.configure(self.button_style, font=("Segoe UI", ttk_font, "bold"), padding=(button_pad, button_pad))
        self.style.configure(self.entry_style, font=("Segoe UI", ttk_font), padding=(entry_pad, entry_pad))
        self.style.configure(self.combo_style, font=("Segoe UI", ttk_font), padding=(combo_pad, combo_pad))
        try:
            self.style.configure(
                self.scale_style,
                sliderthickness=slider_thickness,
                sliderlength=max(18, int(24 * scale)),
                troughcolor="#d7e4ea",
                background="#e05a47",
                troughrelief="flat",
                borderwidth=0,
            )
            self.style.map(self.scale_style, background=[("active", "#c84b39")])
        except tk.TclError:
            # Some themes expose fewer style knobs; keep a safe fallback.
            pass

        if hasattr(self, "controls"):
            self.controls.pack_configure(padx=pad_x, pady=pad_y)
        if hasattr(self, "entry"):
            self.entry.configure(width=entry_chars)
            try:
                self.entry.configure(font=("Segoe UI", ttk_font))
            except tk.TclError:
                pass
        if hasattr(self, "down_btn"):
            self.down_btn.configure(width=btn_chars)
        if hasattr(self, "up_btn"):
            self.up_btn.configure(width=btn_chars)

        mode = self.mode_var.get()
        if hasattr(self, "big_value"):
            if mode == "number":
                value_font = max(20, int(min(width * 0.20, height * 0.28)))
            elif mode == "slider":
                value_font = max(16, int(min(width * 0.15, height * 0.20)))
            else:
                # Dial mode needs extra margin so descenders are not clipped.
                value_font = max(12, int(min(width * 0.12, height * 0.11)))
            self.big_value.configure(font=("Segoe UI", value_font, "bold"))

        if mode == "dial" and hasattr(self, "dial"):
            control_block_h = max(44, int(46 * scale))
            value_block_h = max(28, int(value_font * 1.6))
            available_for_dial = height - header_h - control_block_h - value_block_h - 18
            dial_size = max(96, min(width - 24, available_for_dial))
            self.dial.configure(width=dial_size, height=dial_size)
            self.dial._draw()

    def _on_mode_selected(self, *_args) -> None:
        self._render_mode()
        self._bind_resize_to_children()

    def _edge_zone(self, root_x: int, root_y: int) -> str | None:
        wx = self.winfo_rootx()
        wy = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        rel_x = root_x - wx
        rel_y = root_y - wy
        zone = 12
        near_right = rel_x >= w - zone
        near_bottom = rel_y >= h - zone
        if near_right and near_bottom:
            return "se"
        if near_bottom:
            return "s"
        if near_right:
            return "e"
        return None

    def _on_edge_motion(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        cursors = {"se": "sizing", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow", None: ""}
        new_cursor = cursors.get(zone)
        if new_cursor != self._cursor_zone:
            self._cursor_zone = new_cursor
            self.configure(cursor=new_cursor)

    def _start_resize(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        if zone is None:
            self._resize_state = None
            return
        self._resize_state = {
            "x": event.x_root,
            "y": event.y_root,
            "width": self.winfo_width(),
            "height": self.winfo_height(),
            "zone": zone,
        }

    def _do_resize(self, event) -> None:
        if not self._resize_state:
            return

        dx = event.x_root - self._resize_state["x"]
        dy = event.y_root - self._resize_state["y"]
        zone = self._resize_state["zone"]
        new_width = self._resize_state["width"]
        new_height = self._resize_state["height"]
        if zone in ("e", "se"):
            new_width = max(self.min_width, self._resize_state["width"] + dx)
        if zone in ("s", "se"):
            new_height = max(self.min_height, self._resize_state["height"] + dy)

        self.configure(width=new_width, height=new_height)
        if self.on_resize is not None:
            self.on_resize(self.definition.key, int(new_width), int(new_height))

    def _stop_resize(self, _event) -> None:
        self._resize_state = None

    def _bind_resize_events(self) -> None:
        for target in (self, self.body):
            target.bind("<Motion>", self._on_edge_motion, add="+")
            target.bind("<ButtonPress-1>", self._start_resize, add="+")
            target.bind("<B1-Motion>", self._do_resize, add="+")
            target.bind("<ButtonRelease-1>", self._stop_resize, add="+")

    def _bind_resize_to_children(self) -> None:
        stack = list(self.body.winfo_children())
        while stack:
            w = stack.pop()
            try:
                w.bind("<Motion>", self._on_edge_motion, add="+")
                w.bind("<ButtonPress-1>", self._start_resize, add="+")
                w.bind("<B1-Motion>", self._do_resize, add="+")
                w.bind("<ButtonRelease-1>", self._stop_resize, add="+")
            except tk.TclError:
                pass
            try:
                stack.extend(w.winfo_children())
            except tk.TclError:
                pass


class RelayWidget(tk.Frame):
    def __init__(self, master, definition: RelayDefinition, value: bool, on_change, on_resize=None):
        super().__init__(master, bg="#fbf7ef", bd=1, relief=tk.RIDGE)
        self.definition = definition
        self.on_change = on_change
        self.on_resize = on_resize
        self.value_var = tk.BooleanVar(value=bool(value))
        self.min_width = 220
        self.min_height = 160
        self._resize_state = None

        self.configure(width=240, height=170)
        self.pack_propagate(False)

        self.header = tk.Frame(self, bg="#244b5a", height=30)
        self.header.pack(fill=tk.X)

        self.title_label = tk.Label(
            self.header,
            text=definition.label,
            bg="#244b5a",
            fg="#f7f5ef",
            font=("Segoe UI", 10, "bold"),
        )
        self.title_label.pack(side=tk.LEFT, padx=8)

        self.body = tk.Frame(self, bg="#fbf7ef")
        self.body.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            self.body,
            text="",
            bg="#fbf7ef",
            fg="#244b5a",
            font=("Segoe UI", 28, "bold"),
        )
        self.status_label.pack(expand=True, pady=(16, 4))

        self.detail_label = tk.Label(
            self.body,
            text="",
            bg="#fbf7ef",
            fg="#5c7280",
            font=("Segoe UI", 10),
        )
        self.detail_label.pack(pady=(0, 8))

        self.toggle_btn = ttk.Button(self.body, text="", command=self._toggle)
        self.toggle_btn.pack(pady=(0, 8))

        self._cursor_zone = None
        self._bind_resize_events()
        self._bind_resize_to_children()

        self._refresh_visual()

    def _bind_resize_events(self) -> None:
        for target in (self, self.body):
            target.bind("<Motion>", self._on_edge_motion, add="+")
            target.bind("<ButtonPress-1>", self._start_resize, add="+")
            target.bind("<B1-Motion>", self._do_resize, add="+")
            target.bind("<ButtonRelease-1>", self._stop_resize, add="+")

    def _bind_resize_to_children(self) -> None:
        stack = list(self.body.winfo_children())
        while stack:
            w = stack.pop()
            try:
                w.bind("<Motion>", self._on_edge_motion, add="+")
                w.bind("<ButtonPress-1>", self._start_resize, add="+")
                w.bind("<B1-Motion>", self._do_resize, add="+")
                w.bind("<ButtonRelease-1>", self._stop_resize, add="+")
            except tk.TclError:
                pass
            try:
                stack.extend(w.winfo_children())
            except tk.TclError:
                pass

    def set_state(self, value: bool) -> None:
        self.value_var.set(bool(value))
        self._refresh_visual()

    def get_state(self) -> bool:
        return bool(self.value_var.get())

    def _toggle(self) -> None:
        new_value = not bool(self.value_var.get())
        self.value_var.set(new_value)
        self._refresh_visual()
        self.on_change(self.definition.key, new_value)

    def _refresh_visual(self) -> None:
        enabled = bool(self.value_var.get())
        body_bg = "#dff3e5" if enabled else "#f6e3e0"
        accent = "#1d6b3f" if enabled else "#9e3b2b"
        detail = "State: active" if enabled else "State: inactive"

        self.body.configure(bg=body_bg)
        self.status_label.configure(text="ON" if enabled else "OFF", bg=body_bg, fg=accent)
        self.detail_label.configure(text=detail, bg=body_bg, fg=accent)
        self.toggle_btn.configure(text="Switch Off" if enabled else "Switch On")

    def _edge_zone(self, root_x: int, root_y: int) -> str | None:
        wx = self.winfo_rootx()
        wy = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        rel_x = root_x - wx
        rel_y = root_y - wy
        zone = 12
        near_right = rel_x >= w - zone
        near_bottom = rel_y >= h - zone
        if near_right and near_bottom:
            return "se"
        if near_bottom:
            return "s"
        if near_right:
            return "e"
        return None

    def _on_edge_motion(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        cursors = {"se": "sizing", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow", None: ""}
        new_cursor = cursors.get(zone)
        if new_cursor != self._cursor_zone:
            self._cursor_zone = new_cursor
            self.configure(cursor=new_cursor)

    def _start_resize(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        if zone is None:
            self._resize_state = None
            return
        self._resize_state = {
            "x": event.x_root,
            "y": event.y_root,
            "width": self.winfo_width(),
            "height": self.winfo_height(),
            "zone": zone,
        }

    def _do_resize(self, event) -> None:
        if not self._resize_state:
            return

        dx = event.x_root - self._resize_state["x"]
        dy = event.y_root - self._resize_state["y"]
        zone = self._resize_state["zone"]
        new_width = self._resize_state["width"]
        new_height = self._resize_state["height"]
        if zone in ("e", "se"):
            new_width = max(self.min_width, self._resize_state["width"] + dx)
        if zone in ("s", "se"):
            new_height = max(self.min_height, self._resize_state["height"] + dy)

        self.configure(width=new_width, height=new_height)
        if self.on_resize is not None:
            self.on_resize(self.definition.key, int(new_width), int(new_height))

    def _stop_resize(self, _event) -> None:
        self._resize_state = None


class AddonRelayWidget(RelayWidget):
    pass


class BinaryWidget(tk.Frame):
    def __init__(self, master, definition: ParameterDefinition, value: float, on_change, on_resize=None):
        super().__init__(master, bg="#fbf7ef", bd=1, relief=tk.RIDGE)
        self.definition = definition
        self.on_change = on_change
        self.on_resize = on_resize
        self.value_var = tk.BooleanVar(value=bool(value))
        self.min_width = 140
        self.min_height = 100
        self._resize_state = None
        self._cursor_zone = None

        self.configure(width=200, height=120)
        self.pack_propagate(False)

        self.header = tk.Frame(self, bg="#244b5a", height=26)
        self.header.pack(fill=tk.X)

        self.title_label = tk.Label(
            self.header,
            text=definition.label,
            bg="#244b5a",
            fg="#f7f5ef",
            font=("Segoe UI", 9, "bold"),
        )
        self.title_label.pack(side=tk.LEFT, padx=6)

        self.body = tk.Frame(self, bg="#fbf7ef")
        self.body.pack(fill=tk.BOTH, expand=True)

        self.status_label = tk.Label(
            self.body,
            text="",
            bg="#fbf7ef",
            fg="#ffffff",
            font=("Segoe UI", 24, "bold"),
        )
        self.status_label.pack(expand=True)

        self.bind("<Button-1>", self._toggle)
        self.body.bind("<Button-1>", self._toggle)
        self.status_label.bind("<Button-1>", self._toggle)

        self._bind_resize_events()

        self._refresh()

    def set_value(self, value: float) -> None:
        self.value_var.set(bool(value))
        self._refresh()

    def get_value(self) -> float:
        return float(self.value_var.get())

    def set_mode(self, mode: str) -> None:
        pass

    def get_mode(self) -> str:
        return "binary"

    def _toggle(self, event=None) -> None:
        new_value = not bool(self.value_var.get())
        self.value_var.set(new_value)
        self._refresh()
        self.on_change(self.definition.key, float(new_value))

    def _refresh(self) -> None:
        enabled = bool(self.value_var.get())
        bg = "#1d6b3f" if enabled else "#9e3b2b"
        text = "ON" if enabled else "OFF"
        self.body.configure(bg=bg)
        self.status_label.configure(text=text, bg=bg)

    def _edge_zone(self, root_x: int, root_y: int) -> str | None:
        wx = self.winfo_rootx()
        wy = self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        rel_x = root_x - wx
        rel_y = root_y - wy
        zone = 12
        near_right = rel_x >= w - zone
        near_bottom = rel_y >= h - zone
        if near_right and near_bottom:
            return "se"
        if near_bottom:
            return "s"
        if near_right:
            return "e"
        return None

    def _on_edge_motion(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        cursors = {"se": "sizing", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow", None: ""}
        new_cursor = cursors.get(zone)
        if new_cursor != self._cursor_zone:
            self._cursor_zone = new_cursor
            self.configure(cursor=new_cursor)

    def _bind_resize_events(self) -> None:
        for target in (self, self.body):
            target.bind("<Motion>", self._on_edge_motion, add="+")
            target.bind("<ButtonPress-1>", self._start_resize, add="+")
            target.bind("<B1-Motion>", self._do_resize, add="+")
            target.bind("<ButtonRelease-1>", self._stop_resize, add="+")

    def _start_resize(self, event) -> None:
        zone = self._edge_zone(event.x_root, event.y_root)
        if zone is None:
            self._resize_state = None
            return
        self._resize_state = {
            "x": event.x_root,
            "y": event.y_root,
            "width": self.winfo_width(),
            "height": self.winfo_height(),
            "zone": zone,
        }

    def _do_resize(self, event) -> None:
        if not self._resize_state:
            return
        dx = event.x_root - self._resize_state["x"]
        dy = event.y_root - self._resize_state["y"]
        zone = self._resize_state["zone"]
        new_width = self._resize_state["width"]
        new_height = self._resize_state["height"]
        if zone in ("e", "se"):
            new_width = max(self.min_width, self._resize_state["width"] + dx)
        if zone in ("s", "se"):
            new_height = max(self.min_height, self._resize_state["height"] + dy)
        self.configure(width=new_width, height=new_height)
        if self.on_resize is not None:
            self.on_resize(self.definition.key, int(new_width), int(new_height))

    def _stop_resize(self, _event) -> None:
        self._resize_state = None
