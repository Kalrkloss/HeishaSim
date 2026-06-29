from __future__ import annotations

import contextlib
import json
import queue
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from .models import CZTAW1_EXTERNAL_SENSOR, CZTAW1_RELAYS, MODEL_SIGNATURES, PARAMETER_BY_KEY, PARAMETERS, RELAYS
from .protocol import HeatPumpState
from .serial_worker import CZTAW1AddonSimulator, HeatPumpSerialServer, SerialSettings, available_serial_ports
from .widgets import AddonRelayWidget, BinaryWidget, ParameterWidget, RelayWidget

CONFIG_FILE = Path.home() / ".heishasim" / "heishasim_config.json"
DEFAULT_VISIBLE_PARAMETERS = [p.key for p in PARAMETERS[:4]]


class ConfigDialog(tk.Toplevel):
    def __init__(self, master, current: dict):
        super().__init__(master)
        self.title("Simulator Settings")
        self.resizable(False, False)
        self.result: dict[str, Any] | None = None

        ports = available_serial_ports()
        models = list(MODEL_SIGNATURES.keys())

        self.port_var = tk.StringVar(value=current.get("port", ""))
        self.model_var = tk.StringVar(value=current.get("model", models[0]))
        self.addon_enabled_var = tk.BooleanVar(value=current.get("addon_enabled", False))
        self.addon_port_var = tk.StringVar(value=current.get("addon_port", ""))
        self.interval_var = tk.StringVar(value=str(current.get("addon_interval", 2.0)))

        content = ttk.Frame(self, padding=12)
        content.grid(row=0, column=0, sticky="nsew")

        ttk.Label(content, text="Heat pump serial port").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(content, values=ports, textvariable=self.port_var, width=30).grid(row=0, column=1, sticky="ew")

        ttk.Label(content, text="Heat pump model").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(content, values=models, textvariable=self.model_var, state="readonly", width=30).grid(row=1, column=1, sticky="ew")

        ttk.Checkbutton(
            content,
            text="Enable CZ-TAW1 simulator (second serial port)",
            variable=self.addon_enabled_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=6)

        ttk.Label(content, text="Addon serial port").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(content, values=ports, textvariable=self.addon_port_var, width=30).grid(row=3, column=1, sticky="ew")

        ttk.Label(content, text="Addon query interval (s)").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(content, textvariable=self.interval_var, width=32).grid(row=4, column=1, sticky="ew")

        actions = ttk.Frame(content)
        actions.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(actions, text="Apply", command=self._apply).pack(side=tk.RIGHT)

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _apply(self) -> None:
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            messagebox.showerror("Invalid value", "Addon interval must be a number.")
            return

        self.result = {
            "port": self.port_var.get().strip(),
            "model": self.model_var.get().strip(),
            "addon_enabled": bool(self.addon_enabled_var.get()),
            "addon_port": self.addon_port_var.get().strip(),
            "addon_interval": max(0.5, interval),
        }
        self.destroy()


class HeishaSimApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("HeishaSim - Panasonic Heat Pump Simulator")
        self.geometry("1240x820")
        self.minsize(980, 680)

        self.state_engine = HeatPumpState()
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.config_data: dict[str, Any] = {
            "port": "",
            "model": "H/J Generic",
            "addon_enabled": False,
            "addon_port": "",
            "addon_interval": 2.0,
            "visible_parameters": list(DEFAULT_VISIBLE_PARAMETERS),
            "visible_relays": [],
            "visible_cz_taw1_relays": [relay.key for relay in CZTAW1_RELAYS],
            "visible_cz_taw1_sensor": True,
            "widget_modes": {},
            "widget_positions": {},
            "widget_sizes": {},
            "relay_states": {relay.key: relay.default for relay in RELAYS},
            "relay_positions": {},
            "relay_sizes": {},
            "cz_taw1_relay_states": {relay.key: relay.default for relay in CZTAW1_RELAYS},
            "cz_taw1_relay_positions": {},
            "cz_taw1_relay_sizes": {},
            "cz_taw1_external_sensor": CZTAW1_EXTERNAL_SENSOR.default,
            "cz_taw1_external_sensor_position": {},
            "cz_taw1_external_sensor_size": {},
            "named_layouts": {},
            "latest_layout": {},
            "startup_layout": "latest",
        }

        self.parameter_flags: dict[str, tk.BooleanVar] = {}
        self.relay_flags: dict[str, tk.BooleanVar] = {}
        self.cz_taw1_relay_flags: dict[str, tk.BooleanVar] = {}
        self.cz_taw1_sensor_flag = tk.BooleanVar(value=True)
        self.widgets: dict[str, tuple[ParameterWidget, int]] = {}
        self.widget_z_order: list[str] = []
        self.relay_widgets: dict[str, tuple[RelayWidget, int]] = {}
        self.relay_z_order: list[str] = []
        self.cz_taw1_relay_widgets: dict[str, tuple[AddonRelayWidget, int]] = {}
        self.cz_taw1_relay_z_order: list[str] = []
        self.cz_taw1_sensor_widget: tuple[ParameterWidget, int] | None = None
        self.dragging = {"item": None, "x": 0, "y": 0}

        self.serial_server: HeatPumpSerialServer | None = None
        self.addon_server: CZTAW1AddonSimulator | None = None
        self._closing = False
        self._log_after_id: str | None = None

        self._load_config()
        self._build_ui()
        self._apply_startup_layout_preference(initial=True)
        self._render_parameter_widgets()
        self._render_relay_widgets()
        self._render_cz_taw1_widgets()
        self._schedule_log_drain()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        menu = tk.Menu(self)
        self.config(menu=menu)

        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Start Simulator", command=self.start_serial)
        file_menu.add_command(label="Stop Simulator", command=self.stop_serial)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menu.add_cascade(label="File", menu=file_menu)

        config_menu = tk.Menu(menu, tearoff=0)
        config_menu.add_command(label="Serial / Model Settings", command=self.open_config_dialog)
        config_menu.add_command(label="Refresh Port List", command=lambda: self._log("Serial ports refreshed."))
        menu.add_cascade(label="Config", menu=config_menu)

        self.layouts_menu = tk.Menu(menu, tearoff=0)
        self.layouts_menu.add_command(label="Save Current Layout As...", command=self._save_layout_as)

        self.load_layout_menu = tk.Menu(self.layouts_menu, tearoff=0)
        self.layouts_menu.add_cascade(label="Load Named Layout", menu=self.load_layout_menu)

        self.delete_layout_menu = tk.Menu(self.layouts_menu, tearoff=0)
        self.layouts_menu.add_cascade(label="Delete Named Layout", menu=self.delete_layout_menu)

        self.layouts_menu.add_separator()
        self.layouts_menu.add_command(label="Auto Arrange", command=self._auto_arrange)

        self.layouts_menu.add_separator()
        self.startup_layout_var = tk.StringVar(value=self.config_data.get("startup_layout", "latest"))
        self.startup_layout_menu = tk.Menu(self.layouts_menu, tearoff=0)
        self.startup_layout_menu.add_radiobutton(
            label="Load Latest Layout At Startup",
            value="latest",
            variable=self.startup_layout_var,
            command=self._on_startup_layout_changed,
        )
        self.startup_layout_menu.add_radiobutton(
            label="Start With Default Layout",
            value="default",
            variable=self.startup_layout_var,
            command=self._on_startup_layout_changed,
        )
        self.layouts_menu.add_cascade(label="Startup Behavior", menu=self.startup_layout_menu)

        menu.add_cascade(label="Layouts", menu=self.layouts_menu)

        self.parameters_menu = tk.Menu(menu, tearoff=0)
        for param in PARAMETERS:
            flag = tk.BooleanVar(value=param.key in self.config_data.get("visible_parameters", []))
            self.parameter_flags[param.key] = flag
            self.parameters_menu.add_checkbutton(
                label=param.label,
                variable=flag,
                command=self._render_parameter_widgets,
            )
        self.parameters_menu.add_separator()
        for relay in RELAYS:
            flag = tk.BooleanVar(value=relay.key in self.config_data.get("visible_relays", []))
            self.relay_flags[relay.key] = flag
            self.parameters_menu.add_checkbutton(
                label=relay.label,
                variable=flag,
                command=self._render_relay_widgets,
            )
        self.parameters_menu.add_separator()
        self.cz_taw1_menu = tk.Menu(self.parameters_menu, tearoff=0)
        self.parameters_menu.add_cascade(label="CZ-TAW1", menu=self.cz_taw1_menu)
        self.cz_taw1_menu_index: int = self.parameters_menu.index("end")  # type: ignore[assignment]
        for relay in CZTAW1_RELAYS:
            flag = tk.BooleanVar(value=relay.key in self.config_data.get("visible_cz_taw1_relays", []))
            self.cz_taw1_relay_flags[relay.key] = flag
            self.cz_taw1_menu.add_checkbutton(
                label=relay.label,
                variable=flag,
                command=self._render_cz_taw1_widgets,
            )
        self.cz_taw1_menu.add_checkbutton(
            label=CZTAW1_EXTERNAL_SENSOR.label,
            variable=self.cz_taw1_sensor_flag,
            command=self._render_cz_taw1_widgets,
        )
        menu.add_cascade(label="Parameters", menu=self.parameters_menu)

        top = tk.Frame(self, bg="#efe6d6")
        top.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(top, bg="#efe6d6", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_rectangle(0, 0, 4000, 4000, fill="#efe6d6", outline="")
        for x in range(0, 4000, 40):
            self.canvas.create_line(x, 0, x, 4000, fill="#e2d7c4")
        for y in range(0, 4000, 40):
            self.canvas.create_line(0, y, 4000, y, fill="#e2d7c4")

        log_frame = tk.Frame(self, bg="#17323a", height=150)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM)
        log_frame.pack_propagate(False)

        tk.Label(
            log_frame,
            text="Simulator Log",
            bg="#17323a",
            fg="#f2f4ef",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=8, pady=(6, 2))

        self.log_text = tk.Text(log_frame, height=7, bg="#0f2228", fg="#d7f2e2", insertbackground="#d7f2e2")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._refresh_layout_menus()
        self._sync_cz_taw1_menu_state()

    def _render_parameter_widgets(self) -> None:
        for widget, window_id in self.widgets.values():
            widget.destroy()
            self.canvas.delete(window_id)
        self.widgets.clear()
        self.widget_z_order.clear()

        visible = [key for key, flag in self.parameter_flags.items() if flag.get()]

        for i, key in enumerate(visible):
            definition = PARAMETER_BY_KEY[key]
            value = self.state_engine.get_value(key)
            is_binary = definition.minimum == 0 and definition.maximum == 1 and definition.step == 1

            if is_binary:
                widget: ParameterWidget | BinaryWidget = BinaryWidget(  # type: ignore[no-redef]
                    self.canvas,
                    definition,
                    value,
                    self._on_parameter_change,
                    on_close=self._close_parameter,
                    on_resize=self._on_widget_resize,
                )
                width = 200
                height = 120
                saved_size = self.config_data.get("widget_sizes", {}).get(key)
                if saved_size:
                    width = max(140, int(saved_size.get("width", 200)))
                    height = max(100, int(saved_size.get("height", 120)))
            else:
                widget = ParameterWidget(
                    self.canvas,
                    definition,
                    value,
                    self._on_parameter_change,
                    on_close=self._close_parameter,
                    on_resize=self._on_widget_resize,
                )

                mode = self.config_data.get("widget_modes", {}).get(key)
                if mode in {"number", "slider", "dial"}:
                    widget.set_mode(mode)

                width = 260
                height = 220
                saved_size = self.config_data.get("widget_sizes", {}).get(key)
                if saved_size:
                    width = max(220, int(saved_size.get("width", 260)))
                    height = max(190, int(saved_size.get("height", 220)))

            widget.configure(width=width, height=height)

            saved_pos = self.config_data.get("widget_positions", {}).get(key)
            if saved_pos:
                x, y = saved_pos["x"], saved_pos["y"]
            else:
                x = 30 + (i % 4) * 290
                y = 30 + (i // 4) * 250

            window_id = self.canvas.create_window(x, y, anchor=tk.NW, window=widget, width=width, height=height)
            self.widgets[key] = (widget, window_id)
            self.widget_z_order.append(key)
            self._bind_drag(widget, window_id, key)
            self._bind_foreground_clicks(widget, key)
            if not is_binary:
                widget.mode_combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _e, k=key, w=widget, wid=window_id: self._on_mode_changed(k, w, wid),  # type: ignore[call-overload]
                    add="+",
                )

        self._reapply_z_order()

    def _render_relay_widgets(self) -> None:
        for widget, window_id in self.relay_widgets.values():
            widget.destroy()
            self.canvas.delete(window_id)
        self.relay_widgets.clear()
        self.relay_z_order.clear()

        visible = [key for key, flag in self.relay_flags.items() if flag.get()]

        for i, key in enumerate(visible):
            relay = next((item for item in RELAYS if item.key == key), None)
            if relay is None:
                continue
            value = self.state_engine.get_relay_state(relay.key)
            widget = RelayWidget(
                self.canvas,
                relay,
                value,
                self._on_relay_change,
                on_close=self._close_relay,
                on_resize=self._on_relay_resize,
            )

            width = 240
            height = 170
            saved_size = self.config_data.get("relay_sizes", {}).get(relay.key)
            if saved_size:
                width = max(220, int(saved_size.get("width", 240)))
                height = max(160, int(saved_size.get("height", 170)))
            widget.configure(width=width, height=height)

            saved_pos = self.config_data.get("relay_positions", {}).get(relay.key)
            if saved_pos:
                x, y = saved_pos["x"], saved_pos["y"]
            else:
                x = 30 + i * 290
                y = 520

            window_id = self.canvas.create_window(x, y, anchor=tk.NW, window=widget, width=width, height=height)
            self.relay_widgets[relay.key] = (widget, window_id)
            self.relay_z_order.append(relay.key)
            self._bind_relay_drag(widget, window_id, relay.key)
            self._bind_foreground_clicks(widget, relay.key, self._bring_relay_to_front)

        self._reapply_relay_z_order()

    def _render_cz_taw1_widgets(self) -> None:
        for widget, window_id in self.cz_taw1_relay_widgets.values():
            widget.destroy()
            self.canvas.delete(window_id)
        self.cz_taw1_relay_widgets.clear()
        self.cz_taw1_relay_z_order.clear()

        if not self.config_data.get("addon_enabled"):
            if self.cz_taw1_sensor_widget is not None:
                sensor_widget, sensor_window_id = self.cz_taw1_sensor_widget
                sensor_widget.destroy()
                self.canvas.delete(sensor_window_id)
                self.cz_taw1_sensor_widget = None
            self._sync_cz_taw1_menu_state()
            return

        visible_relays = [key for key, flag in self.cz_taw1_relay_flags.items() if flag.get()]

        for i, key in enumerate(visible_relays):
            relay = next((item for item in CZTAW1_RELAYS if item.key == key), None)
            if relay is None:
                continue
            value = self.state_engine.get_cz_taw1_relay_state(relay.key)
            widget = AddonRelayWidget(
                self.canvas,
                relay,
                value,
                self._on_cz_taw1_relay_change,
                on_close=self._close_cz_taw1_item,
                on_resize=self._on_cz_taw1_relay_resize,
            )

            width = 240
            height = 170
            saved_size = self.config_data.get("cz_taw1_relay_sizes", {}).get(relay.key)
            if saved_size:
                width = max(220, int(saved_size.get("width", 240)))
                height = max(160, int(saved_size.get("height", 170)))
            widget.configure(width=width, height=height)

            saved_pos = self.config_data.get("cz_taw1_relay_positions", {}).get(relay.key)
            if saved_pos:
                x, y = saved_pos["x"], saved_pos["y"]
            else:
                x = 30 + (i % 3) * 290
                y = 430

            window_id = self.canvas.create_window(x, y, anchor=tk.NW, window=widget, width=width, height=height)
            self.cz_taw1_relay_widgets[relay.key] = (widget, window_id)
            self.cz_taw1_relay_z_order.append(relay.key)
            self._bind_cz_taw1_relay_drag(widget, window_id, relay.key, self._bring_cz_taw1_widget_to_front)
            self._bind_foreground_clicks(widget, relay.key, self._bring_cz_taw1_widget_to_front)

        if self.cz_taw1_sensor_flag.get():
            sensor_value: float = self.state_engine.get_cz_taw1_external_sensor_temp()
            sensor_widget = ParameterWidget(
                self.canvas,
                CZTAW1_EXTERNAL_SENSOR,
                sensor_value,
                self._on_cz_taw1_sensor_change,
                on_close=self._close_cz_taw1_item,
                on_resize=self._on_cz_taw1_sensor_resize,
            )

            width = 260
            height = 220
            saved_size = self.config_data.get("cz_taw1_external_sensor_size", {})
            if saved_size:
                width = max(220, int(saved_size.get("width", 260)))
                height = max(190, int(saved_size.get("height", 220)))
            sensor_widget.configure(width=width, height=height)

            saved_pos = self.config_data.get("cz_taw1_external_sensor_position", {})
            if saved_pos:
                x, y = saved_pos["x"], saved_pos["y"]
            else:
                x = 30 + (len(CZTAW1_RELAYS) % 3) * 290
                y = 430

            window_id = self.canvas.create_window(x, y, anchor=tk.NW, window=sensor_widget, width=width, height=height)
            self.cz_taw1_sensor_widget = (sensor_widget, window_id)
            self.cz_taw1_relay_z_order.append(CZTAW1_EXTERNAL_SENSOR.key)
            self._bind_drag(sensor_widget, window_id, CZTAW1_EXTERNAL_SENSOR.key, self._bring_cz_taw1_widget_to_front)
            self._bind_foreground_clicks(sensor_widget, CZTAW1_EXTERNAL_SENSOR.key, self._bring_cz_taw1_widget_to_front)
        else:
            if self.cz_taw1_sensor_widget is not None:
                sensor_widget, sensor_window_id = self.cz_taw1_sensor_widget
                sensor_widget.destroy()
                self.canvas.delete(sensor_window_id)
                self.cz_taw1_sensor_widget = None

        self._reapply_cz_taw1_relay_z_order()
        self._sync_cz_taw1_menu_state()

    def _reapply_z_order(self) -> None:
        for key in self.widget_z_order:
            widget_pair = self.widgets.get(key)
            if widget_pair is None:
                continue
            widget, window_id = widget_pair
            self.canvas.tag_raise(window_id)
            with contextlib.suppress(tk.TclError):
                widget.lift()

    def _reapply_relay_z_order(self) -> None:
        for key in self.relay_z_order:
            widget_pair = self.relay_widgets.get(key)
            if widget_pair is None:
                continue
            widget, window_id = widget_pair
            self.canvas.tag_raise(window_id)
            with contextlib.suppress(tk.TclError):
                widget.lift()

    def _reapply_cz_taw1_relay_z_order(self) -> None:
        for key in self.cz_taw1_relay_z_order:
            widget_pair = self.cz_taw1_relay_widgets.get(key)
            if widget_pair is None:
                continue
            widget, window_id = widget_pair
            self.canvas.tag_raise(window_id)
            with contextlib.suppress(tk.TclError):
                widget.lift()
        if self.cz_taw1_sensor_widget is not None:
            _, sensor_window = self.cz_taw1_sensor_widget
            self.canvas.tag_raise(sensor_window)

    def _bring_widget_to_front(self, key: str) -> None:
        # Move the bookkeeping list (preserves tests' widget_z_order[-1] == key
        # expectation and within-group order hints after a fresh render) and
        # then raise ONLY the target canvas window above all other canvas items.
        # Raising all parameters here (via _reapply_z_order) could put the
        # clicked parameter above other parameters, but it could also disturb
        # the relative order between parameters and other widget types. A
        # single tag_raise on the target window brings it to the absolute
        # foreground regardless of which other widget type is on top.
        if key not in self.widget_z_order:
            return
        self.widget_z_order = [k for k in self.widget_z_order if k != key]
        self.widget_z_order.append(key)
        widget_pair = self.widgets.get(key)
        if widget_pair is None:
            return
        widget, window_id = widget_pair
        self.canvas.tag_raise(window_id)
        with contextlib.suppress(tk.TclError):
            widget.lift()

    def _bring_relay_to_front(self, key: str) -> None:
        # Single-window raise for the same reason as _bring_widget_to_front:
        # a full _reapply_relay_z_order only touches relay windows and can
        # leave a relay below CZ-TAW1 widgets even after reordering. Targeting
        # just the key window with tag_raise lifts it above every canvas item.
        if key not in self.relay_z_order:
            return
        self.relay_z_order = [k for k in self.relay_z_order if k != key]
        self.relay_z_order.append(key)
        widget_pair = self.relay_widgets.get(key)
        if widget_pair is None:
            return
        widget, window_id = widget_pair
        self.canvas.tag_raise(window_id)
        with contextlib.suppress(tk.TclError):
            widget.lift()

    def _bring_cz_taw1_widget_to_front(self, key: str) -> None:
        widget_pair = self.cz_taw1_relay_widgets.get(key)
        if widget_pair is not None:
            widget, window_id = widget_pair
            self.canvas.tag_raise(window_id)
            with contextlib.suppress(tk.TclError):
                widget.lift()
            return
        if self.cz_taw1_sensor_widget is not None and key == CZTAW1_EXTERNAL_SENSOR.key:
            _, sensor_window = self.cz_taw1_sensor_widget
            self.canvas.tag_raise(sensor_window)

    def _bind_foreground_clicks(self, root_widget: tk.Widget, key: str, bring_to_front: Callable[[str], None] | None = None) -> None:
        if bring_to_front is None:
            bring_to_front = self._bring_widget_to_front

        def _bring(_event, widget_key=key):
            bring_to_front(widget_key)

        stack = [root_widget]
        while stack:
            widget = stack.pop()
            with contextlib.suppress(tk.TclError):
                widget.bind("<ButtonPress-1>", _bring, add="+")
            with contextlib.suppress(tk.TclError):
                stack.extend(widget.winfo_children())  # type: ignore[arg-type]

    def _on_mode_changed(self, key: str, widget: ParameterWidget, window_id: int) -> None:
        self._remember_mode(key)
        # Mode switch rebuilds controls; rebind click-to-front on the new widget subtree.
        self.after_idle(lambda: self._bind_foreground_clicks(widget, key))

    def _on_relay_change(self, key: str, value: bool) -> None:
        self.state_engine.set_relay_state(key, value)
        self.config_data.setdefault("relay_states", {})[key] = bool(value)

    def _on_relay_resize(self, key: str, width: int, height: int) -> None:
        self.config_data.setdefault("relay_sizes", {})[key] = {
            "width": int(width),
            "height": int(height),
        }
        self._bring_relay_to_front(key)
        widget_pair = self.relay_widgets.get(key)
        if widget_pair is not None:
            _, window_id = widget_pair
            self.canvas.itemconfigure(window_id, width=int(width), height=int(height))

    def _on_cz_taw1_relay_change(self, key: str, value: bool) -> None:
        self.state_engine.set_cz_taw1_relay_state(key, value)
        self.config_data.setdefault("cz_taw1_relay_states", {})[key] = bool(value)

    def _on_cz_taw1_relay_resize(self, key: str, width: int, height: int) -> None:
        self.config_data.setdefault("cz_taw1_relay_sizes", {})[key] = {
            "width": int(width),
            "height": int(height),
        }
        self._bring_cz_taw1_widget_to_front(key)
        widget_pair = self.cz_taw1_relay_widgets.get(key)
        if widget_pair is not None:
            _, window_id = widget_pair
            self.canvas.itemconfigure(window_id, width=int(width), height=int(height))

    def _on_cz_taw1_sensor_change(self, key: str, value: float) -> None:
        if key != CZTAW1_EXTERNAL_SENSOR.key:
            return
        self.state_engine.set_cz_taw1_external_sensor_temp(value)
        self.config_data["cz_taw1_external_sensor"] = float(value)

    def _on_cz_taw1_sensor_resize(self, key: str, width: int, height: int) -> None:
        self.config_data.setdefault("cz_taw1_external_sensor_position", {})
        self.config_data["cz_taw1_external_sensor_size"] = {
            "width": int(width),
            "height": int(height),
        }
        widget_pair = self.cz_taw1_sensor_widget
        if widget_pair is not None:
            _, window_id = widget_pair
            self.canvas.itemconfigure(window_id, width=int(width), height=int(height))

    def _close_parameter(self, key: str) -> None:
        """Close button handler for parameter widgets.

        Flips the visibility flag, removes the key from persistent config
        (so the widget stays closed across reloads), and re-renders. Mirrors
        the existing Parameters menu toggle UX.
        """
        flag = self.parameter_flags.get(key)
        if flag is not None and flag.get():
            flag.set(False)
        visible = self.config_data.get("visible_parameters", [])
        if key in visible:
            self.config_data["visible_parameters"] = [k for k in visible if k != key]
        self._render_parameter_widgets()
        self._log(f"Closed parameter widget: {key}")

    def _close_relay(self, key: str) -> None:
        """Close button handler for relay widgets."""
        flag = self.relay_flags.get(key)
        if flag is not None and flag.get():
            flag.set(False)
        visible = self.config_data.get("visible_relays", [])
        if key in visible:
            self.config_data["visible_relays"] = [k for k in visible if k != key]
        self._render_relay_widgets()
        self._log(f"Closed relay widget: {key}")

    def _close_cz_taw1_item(self, key: str) -> None:
        """Close button handler for CZ-TAW1 relays or the external sensor."""
        relay_flag = self.cz_taw1_relay_flags.get(key)
        if relay_flag is not None and relay_flag.get():
            relay_flag.set(False)
        if key == CZTAW1_EXTERNAL_SENSOR.key and self.cz_taw1_sensor_flag.get():
            self.cz_taw1_sensor_flag.set(False)
        visible_relays = self.config_data.get("visible_cz_taw1_relays", [])
        if key in visible_relays:
            self.config_data["visible_cz_taw1_relays"] = [
                k for k in visible_relays if k != key
            ]
        self._render_cz_taw1_widgets()
        self._log(f"Closed CZ-TAW1 widget: {key}")

    def _bind_cz_taw1_relay_drag(self, widget: AddonRelayWidget, window_id: int, key: str, bring_to_front: Callable[[str], None] | None = None) -> None:
        if bring_to_front is None:
            bring_to_front = self._bring_cz_taw1_widget_to_front

        def start(event):
            bring_to_front(key)
            self.dragging["item"] = window_id
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def drag(event):
            if self.dragging["item"] != window_id:
                return
            dx = event.x_root - self.dragging["x"]
            dy = event.y_root - self.dragging["y"]
            self.canvas.move(window_id, dx, dy)
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def stop(_event):
            if self.dragging["item"] != window_id:
                return
            self.dragging["item"] = None
            coords = self.canvas.coords(window_id)
            if coords:
                self.config_data.setdefault("cz_taw1_relay_positions", {})[key] = {
                    "x": int(coords[0]),
                    "y": int(coords[1]),
                }

        widget.header.bind("<ButtonPress-1>", start)
        widget.header.bind("<B1-Motion>", drag)
        widget.header.bind("<ButtonRelease-1>", stop)
        widget.title_label.bind("<ButtonPress-1>", start)
        widget.title_label.bind("<B1-Motion>", drag)
        widget.title_label.bind("<ButtonRelease-1>", stop)

    def _sync_cz_taw1_menu_state(self) -> None:
        addon_enabled = bool(self.config_data.get("addon_enabled"))
        with contextlib.suppress(tk.TclError):
            self.parameters_menu.entryconfig(self.cz_taw1_menu_index, state=(tk.NORMAL if addon_enabled else tk.DISABLED))

    def _bind_drag(self, widget: ParameterWidget, window_id: int, key: str, bring_to_front: Callable[[str], None] | None = None) -> None:
        if bring_to_front is None:
            bring_to_front = self._bring_widget_to_front

        def start(event):
            bring_to_front(key)
            self.dragging["item"] = window_id
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def drag(event):
            if self.dragging["item"] != window_id:
                return
            dx = event.x_root - self.dragging["x"]
            dy = event.y_root - self.dragging["y"]
            self.canvas.move(window_id, dx, dy)
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def stop(_event):
            if self.dragging["item"] != window_id:
                return
            self.dragging["item"] = None
            coords = self.canvas.coords(window_id)
            if coords:
                self.config_data.setdefault("widget_positions", {})[key] = {
                    "x": int(coords[0]),
                    "y": int(coords[1]),
                }

        widget.header.bind("<ButtonPress-1>", start)
        widget.header.bind("<B1-Motion>", drag)
        widget.header.bind("<ButtonRelease-1>", stop)
        widget.title_label.bind("<ButtonPress-1>", start)
        widget.title_label.bind("<B1-Motion>", drag)
        widget.title_label.bind("<ButtonRelease-1>", stop)

    def _bind_relay_drag(self, widget: RelayWidget, window_id: int, key: str) -> None:
        def start(event):
            self._bring_relay_to_front(key)
            self.dragging["item"] = window_id
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def drag(event):
            if self.dragging["item"] != window_id:
                return
            dx = event.x_root - self.dragging["x"]
            dy = event.y_root - self.dragging["y"]
            self.canvas.move(window_id, dx, dy)
            self.dragging["x"] = event.x_root
            self.dragging["y"] = event.y_root

        def stop(_event):
            if self.dragging["item"] != window_id:
                return
            self.dragging["item"] = None
            coords = self.canvas.coords(window_id)
            if coords:
                self.config_data.setdefault("relay_positions", {})[key] = {
                    "x": int(coords[0]),
                    "y": int(coords[1]),
                }

        widget.header.bind("<ButtonPress-1>", start)
        widget.header.bind("<B1-Motion>", drag)
        widget.header.bind("<ButtonRelease-1>", stop)
        widget.title_label.bind("<ButtonPress-1>", start)
        widget.title_label.bind("<B1-Motion>", drag)
        widget.title_label.bind("<ButtonRelease-1>", stop)

    def _remember_mode(self, key: str) -> None:
        widget = self.widgets.get(key)
        if not widget:
            return
        control = widget[0]
        self.config_data.setdefault("widget_modes", {})[key] = control.get_mode()

    def _capture_current_layout(self) -> dict:
        visible_parameters = [k for k, v in self.parameter_flags.items() if v.get()]
        visible_relays = [k for k, v in self.relay_flags.items() if v.get()]
        visible_cz_taw1_relays = [k for k, v in self.cz_taw1_relay_flags.items() if v.get()]
        return {
            "visible_parameters": list(visible_parameters),
            "visible_relays": list(visible_relays),
            "visible_cz_taw1_relays": list(visible_cz_taw1_relays),
            "visible_cz_taw1_sensor": bool(self.cz_taw1_sensor_flag.get()),
            "widget_modes": dict(self.config_data.get("widget_modes", {})),
            "widget_positions": dict(self.config_data.get("widget_positions", {})),
            "widget_sizes": dict(self.config_data.get("widget_sizes", {})),
            "relay_states": dict(self.config_data.get("relay_states", {})),
            "relay_positions": dict(self.config_data.get("relay_positions", {})),
            "relay_sizes": dict(self.config_data.get("relay_sizes", {})),
            "cz_taw1_relay_states": dict(self.config_data.get("cz_taw1_relay_states", {})),
            "cz_taw1_relay_positions": dict(self.config_data.get("cz_taw1_relay_positions", {})),
            "cz_taw1_relay_sizes": dict(self.config_data.get("cz_taw1_relay_sizes", {})),
            "cz_taw1_external_sensor": float(self.config_data.get("cz_taw1_external_sensor", CZTAW1_EXTERNAL_SENSOR.default)),
            "cz_taw1_external_sensor_position": dict(self.config_data.get("cz_taw1_external_sensor_position", {})),
            "cz_taw1_external_sensor_size": dict(self.config_data.get("cz_taw1_external_sensor_size", {})),
        }

    def _default_layout(self) -> dict:
        return {
            "visible_parameters": list(DEFAULT_VISIBLE_PARAMETERS),
            "visible_relays": [],
            "visible_cz_taw1_relays": [relay.key for relay in CZTAW1_RELAYS],
            "visible_cz_taw1_sensor": True,
            "widget_modes": {},
            "widget_positions": {},
            "widget_sizes": {},
            "relay_states": {relay.key: relay.default for relay in RELAYS},
            "relay_positions": {},
            "relay_sizes": {},
            "cz_taw1_relay_states": {relay.key: relay.default for relay in CZTAW1_RELAYS},
            "cz_taw1_relay_positions": {},
            "cz_taw1_relay_sizes": {},
            "cz_taw1_external_sensor": CZTAW1_EXTERNAL_SENSOR.default,
            "cz_taw1_external_sensor_position": {},
            "cz_taw1_external_sensor_size": {},
        }

    def _apply_layout(self, layout: dict, rerender: bool = True) -> None:
        visible = layout.get("visible_parameters", DEFAULT_VISIBLE_PARAMETERS)
        self.config_data["visible_parameters"] = list(visible)
        self.config_data["visible_relays"] = list(layout.get("visible_relays", self.config_data.get("visible_relays", [relay.key for relay in RELAYS])))
        self.config_data["visible_cz_taw1_relays"] = list(
            layout.get("visible_cz_taw1_relays", self.config_data.get("visible_cz_taw1_relays", [relay.key for relay in CZTAW1_RELAYS]))
        )
        self.config_data["visible_cz_taw1_sensor"] = bool(
            layout.get("visible_cz_taw1_sensor", self.config_data.get("visible_cz_taw1_sensor", True))
        )
        self.config_data["widget_modes"] = dict(layout.get("widget_modes", {}))
        self.config_data["widget_positions"] = dict(layout.get("widget_positions", {}))
        self.config_data["widget_sizes"] = dict(layout.get("widget_sizes", {}))
        self.config_data["relay_states"] = dict(layout.get("relay_states", self.config_data.get("relay_states", {})))
        self.config_data["relay_positions"] = dict(layout.get("relay_positions", {}))
        self.config_data["relay_sizes"] = dict(layout.get("relay_sizes", {}))
        self.config_data["cz_taw1_relay_states"] = dict(
            layout.get("cz_taw1_relay_states", self.config_data.get("cz_taw1_relay_states", {}))
        )
        self.config_data["cz_taw1_relay_positions"] = dict(layout.get("cz_taw1_relay_positions", {}))
        self.config_data["cz_taw1_relay_sizes"] = dict(layout.get("cz_taw1_relay_sizes", {}))
        self.config_data["cz_taw1_external_sensor"] = float(
            layout.get("cz_taw1_external_sensor", self.config_data.get("cz_taw1_external_sensor", CZTAW1_EXTERNAL_SENSOR.default))
        )
        self.config_data["cz_taw1_external_sensor_position"] = dict(layout.get("cz_taw1_external_sensor_position", {}))
        self.config_data["cz_taw1_external_sensor_size"] = dict(layout.get("cz_taw1_external_sensor_size", {}))

        for key, flag in self.parameter_flags.items():
            flag.set(key in self.config_data["visible_parameters"])

        for key, flag in self.relay_flags.items():
            flag.set(key in self.config_data["visible_relays"])

        for key, flag in self.cz_taw1_relay_flags.items():
            flag.set(key in self.config_data["visible_cz_taw1_relays"])

        self.cz_taw1_sensor_flag.set(bool(self.config_data.get("visible_cz_taw1_sensor", True)))

        for relay in RELAYS:
            self.state_engine.set_relay_state(relay.key, bool(self.config_data["relay_states"].get(relay.key, relay.default)))

        for relay in CZTAW1_RELAYS:
            self.state_engine.set_cz_taw1_relay_state(
                relay.key,
                bool(self.config_data["cz_taw1_relay_states"].get(relay.key, relay.default)),
            )
        self.state_engine.set_cz_taw1_external_sensor_temp(self.config_data["cz_taw1_external_sensor"])

        if rerender:
            self._render_parameter_widgets()
            self._render_relay_widgets()
            self._render_cz_taw1_widgets()

    def _save_layout_as(self) -> None:
        name = simpledialog.askstring("Save Layout", "Layout name:", parent=self)
        if name is None:
            return

        name = name.strip()
        if not name:
            messagebox.showwarning("Invalid name", "Layout name cannot be empty.")
            return

        named_layouts = self.config_data.setdefault("named_layouts", {})
        named_layouts[name] = self._capture_current_layout()
        self._refresh_layout_menus()
        self._log(f"Saved layout '{name}'.")

    def _load_named_layout(self, name: str) -> None:
        named_layouts = self.config_data.get("named_layouts", {})
        layout = named_layouts.get(name)
        if not isinstance(layout, dict):
            messagebox.showwarning("Layout missing", f"Layout '{name}' was not found.")
            self._refresh_layout_menus()
            return

        self._apply_layout(layout, rerender=True)
        self.config_data["latest_layout"] = self._capture_current_layout()
        self._log(f"Loaded layout '{name}'.")

    def _delete_named_layout(self, name: str) -> None:
        named_layouts = self.config_data.get("named_layouts", {})
        if name not in named_layouts:
            return
        if not messagebox.askyesno("Delete Layout", f"Delete layout '{name}'?"):
            return

        del named_layouts[name]
        self._refresh_layout_menus()
        self._log(f"Deleted layout '{name}'.")

    def _refresh_layout_menus(self) -> None:
        names = sorted(self.config_data.get("named_layouts", {}).keys())

        self.load_layout_menu.delete(0, tk.END)
        self.delete_layout_menu.delete(0, tk.END)

        if not names:
            self.load_layout_menu.add_command(label="(No saved layouts)", state=tk.DISABLED)
            self.delete_layout_menu.add_command(label="(No saved layouts)", state=tk.DISABLED)
            return

        for name in names:
            self.load_layout_menu.add_command(label=name, command=lambda n=name: self._load_named_layout(n))  # type: ignore[misc]
            self.delete_layout_menu.add_command(label=name, command=lambda n=name: self._delete_named_layout(n))  # type: ignore[misc]

    def _auto_arrange(self) -> None:
        self.config_data["widget_positions"] = {}
        self.config_data["widget_sizes"] = {}
        self.config_data["relay_positions"] = {}
        self.config_data["relay_sizes"] = {}
        self.config_data["cz_taw1_relay_positions"] = {}
        self.config_data["cz_taw1_relay_sizes"] = {}
        self.config_data["cz_taw1_external_sensor_position"] = {}
        self.config_data["cz_taw1_external_sensor_size"] = {}
        self._render_parameter_widgets()
        self._render_relay_widgets()
        self._render_cz_taw1_widgets()
        self._log("Auto-arranged all widgets.")

    def _on_startup_layout_changed(self) -> None:
        self.config_data["startup_layout"] = self.startup_layout_var.get()

    def _apply_startup_layout_preference(self, initial: bool = False) -> None:
        startup_mode = self.config_data.get("startup_layout", "latest")
        latest_layout = self.config_data.get("latest_layout", {})

        if startup_mode == "latest" and isinstance(latest_layout, dict) and latest_layout:
            self._apply_layout(latest_layout, rerender=not initial)
            return

        if startup_mode == "default":
            self._apply_layout(self._default_layout(), rerender=not initial)

    def _on_parameter_change(self, key: str, value: float) -> None:
        self.state_engine.set_value(key, value)

    def _on_widget_resize(self, key: str, width: int, height: int) -> None:
        self.config_data.setdefault("widget_sizes", {})[key] = {
            "width": int(width),
            "height": int(height),
        }
        self._bring_widget_to_front(key)
        widget_pair = self.widgets.get(key)
        if widget_pair is not None:
            _, window_id = widget_pair
            self.canvas.itemconfigure(window_id, width=int(width), height=int(height))

    def open_config_dialog(self) -> None:
        dlg = ConfigDialog(self, self.config_data)
        self.wait_window(dlg)
        if dlg.result is None:
            return

        self.config_data.update(dlg.result)
        self.state_engine.set_model(self.config_data["model"])
        self._sync_cz_taw1_menu_state()
        self._render_cz_taw1_widgets()
        self._log(
            f"Configured model={self.config_data['model']}, port={self.config_data['port']}, "
            f"addon={'on' if self.config_data['addon_enabled'] else 'off'}"
        )

    def start_serial(self) -> None:
        port = self.config_data.get("port", "").strip()
        if not port:
            messagebox.showwarning("Missing port", "Please select the heat pump serial port in Config.")
            return

        self.stop_serial()
        self.state_engine.set_model(self.config_data.get("model", "H/J Generic"))

        self.serial_server = HeatPumpSerialServer(
            settings=SerialSettings(port=port),
            state=self.state_engine,
            on_status=self._queue_log,
            on_frame=self._queue_log,
        )
        self.serial_server.start()

        if self.config_data.get("addon_enabled"):
            addon_port: str = self.config_data.get("addon_port", "").strip()
            if addon_port:
                self.addon_server = CZTAW1AddonSimulator(
                    settings=SerialSettings(port=addon_port),
                    on_status=self._queue_log,
                    on_frame=self._queue_log,
                    interval_seconds=float(self.config_data.get("addon_interval", 2.0)),
                    send_extra_query=True,
                )
                self.addon_server.start()
            else:
                self._log("Addon simulator enabled but no addon port selected.")

        self._log("Simulator started.")

    def stop_serial(self) -> None:
        serial_thread = self.serial_server
        addon_thread = self.addon_server

        if serial_thread is not None:
            serial_thread.stop()
            serial_thread.join(timeout=1.5)
            self.serial_server = None

        if addon_thread is not None:
            addon_thread.stop()
            addon_thread.join(timeout=1.5)
            self.addon_server = None

        if serial_thread is not None and serial_thread.is_alive():
            self._log("Heat pump serial thread did not stop within timeout.")
        if addon_thread is not None and addon_thread.is_alive():
            self._log("CZ-TAW1 thread did not stop within timeout.")
        self._log("Simulator stopped.")

    def _queue_log(self, line: str) -> None:
        self.log_queue.put(line)

    def _schedule_log_drain(self) -> None:
        if self._closing:
            return
        while not self.log_queue.empty():
            self._log(self.log_queue.get_nowait())
        self._log_after_id = self.after(120, self._schedule_log_drain)

    def _log(self, line: str) -> None:
        try:
            if self._closing:
                return
            self.log_text.insert(tk.END, f"{line}\n")
            self.log_text.see(tk.END)
        except tk.TclError:
            # App is shutting down and widgets may already be gone.
            return

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            return
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.config_data.update(loaded)
                self.config_data.setdefault("named_layouts", {})
                self.config_data.setdefault("latest_layout", {})
                self.config_data.setdefault("startup_layout", "latest")
                self.config_data.setdefault("visible_parameters", list(DEFAULT_VISIBLE_PARAMETERS))
                self.config_data.setdefault("visible_relays", [])
                self.config_data.setdefault("visible_cz_taw1_relays", [relay.key for relay in CZTAW1_RELAYS])
                self.config_data.setdefault("visible_cz_taw1_sensor", True)
                self.config_data.setdefault("widget_modes", {})
                self.config_data.setdefault("widget_positions", {})
                self.config_data.setdefault("widget_sizes", {})
                self.config_data.setdefault("relay_states", {relay.key: relay.default for relay in RELAYS})
                self.config_data.setdefault("relay_positions", {})
                self.config_data.setdefault("relay_sizes", {})
                self.config_data.setdefault("cz_taw1_relay_states", {relay.key: relay.default for relay in CZTAW1_RELAYS})
                self.config_data.setdefault("cz_taw1_relay_positions", {})
                self.config_data.setdefault("cz_taw1_relay_sizes", {})
                self.config_data.setdefault("cz_taw1_external_sensor", CZTAW1_EXTERNAL_SENSOR.default)
                self.config_data.setdefault("cz_taw1_external_sensor_position", {})
                self.config_data.setdefault("cz_taw1_external_sensor_size", {})
                model = self.config_data.get("model", "H/J Generic")
                self.state_engine.set_model(model)
                for relay in RELAYS:
                    self.state_engine.set_relay_state(relay.key, bool(self.config_data["relay_states"].get(relay.key, relay.default)))
                for relay in CZTAW1_RELAYS:
                    self.state_engine.set_cz_taw1_relay_state(
                        relay.key,
                        bool(self.config_data["cz_taw1_relay_states"].get(relay.key, relay.default)),
                    )
                self.state_engine.set_cz_taw1_external_sensor_temp(self.config_data["cz_taw1_external_sensor"])
        except Exception:
            pass

    def _save_config(self) -> None:
        self.config_data["visible_parameters"] = [k for k, v in self.parameter_flags.items() if v.get()]
        self.config_data["visible_relays"] = [k for k, v in self.relay_flags.items() if v.get()]
        self.config_data["visible_cz_taw1_relays"] = [k for k, v in self.cz_taw1_relay_flags.items() if v.get()]
        self.config_data["visible_cz_taw1_sensor"] = bool(self.cz_taw1_sensor_flag.get())
        self.config_data["cz_taw1_relay_states"] = {
            relay.key: self.state_engine.get_cz_taw1_relay_state(relay.key) for relay in CZTAW1_RELAYS
        }
        self.config_data["cz_taw1_external_sensor"] = self.state_engine.get_cz_taw1_external_sensor_temp()
        self.config_data["latest_layout"] = self._capture_current_layout()
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.config_data, indent=2), encoding="utf-8")

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True

        if self._log_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._log_after_id)
            self._log_after_id = None

        try:
            self.stop_serial()
            self._save_config()
        finally:
            # Ensure the Tk event loop exits even if shutdown steps throw.
            with contextlib.suppress(tk.TclError):
                self.quit()
            with contextlib.suppress(tk.TclError):
                self.destroy()


def main() -> None:
    app = HeishaSimApp()
    app.mainloop()
