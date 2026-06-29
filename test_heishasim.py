"""
Automated UI test for HeishaSim - exercises widgets, dragging, values, layouts.
Runs the Tkinter app programmatically and tests all major interactions.
"""
from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path

# Add the project to path
sys.path.insert(0, str(Path(__file__).parent))

from heishasim.app import CONFIG_FILE, DEFAULT_VISIBLE_PARAMETERS, HeishaSimApp
from heishasim.models import PARAMETERS, RELAYS


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors: list[str] = []

    def ok(self, msg: str):
        self.passed += 1
        print(f"  [PASS] {msg}")

    def fail(self, msg: str):
        self.failed += 1
        self.errors.append(msg)
        print(f"  [FAIL] {msg}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            for e in self.errors:
                print(f"  FAIL: {e}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResults()


def assert_true(cond, msg: str):
    if cond:
        results.ok(msg)
    else:
        results.fail(msg)


def assert_equal(a, b, msg: str):
    if a == b:
        results.ok(f"{msg} (got {a!r})")
    else:
        results.fail(f"{msg}: expected {b!r}, got {a!r}")


def find_widget_by_key(app: HeishaSimApp, key: str):
    """Find a ParameterWidget by its parameter key."""
    pair = app.widgets.get(key)
    if pair:
        return pair[0]
    return None


def find_relay_widget(app: HeishaSimApp, key: str):
    pair = app.relay_widgets.get(key)
    if pair:
        return pair[0]
    return None


def run_tests():
    # Backup existing config if any
    config_backup = None
    if CONFIG_FILE.exists():
        config_backup = CONFIG_FILE.read_text(encoding="utf-8")

    # Remove config to start fresh
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()

    try:
        app = HeishaSimApp()

        # Schedule tests after the app has initialized
        def run_all_tests():
            try:
                # ============================================================
                # TEST 1: Initial state
                # ============================================================
                print("\n--- Test 1: Initial State ---")

                assert_equal(
                    len(app.widgets),
                    len(DEFAULT_VISIBLE_PARAMETERS),
                    "Initial visible widgets count"
                )
                assert_equal(len(app.relay_widgets), 0, "No relay widgets initially")

                visible_keys = [k for k, v in app.parameter_flags.items() if v.get()]
                assert_equal(
                    set(visible_keys),
                    set(DEFAULT_VISIBLE_PARAMETERS),
                    "Default visible parameter keys"
                )

                # ============================================================
                # TEST 2: Open additional parameter widgets
                # ============================================================
                print("\n--- Test 2: Open Additional Widgets ---")

                # Enable all parameters
                for key, flag in app.parameter_flags.items():
                    if not flag.get():
                        flag.set(True)
                        print(f"  Enabling widget: {key}")

                app._render_parameter_widgets()
                expected = len(PARAMETERS)
                assert_equal(
                    len(app.widgets),
                    expected,
                    f"All {expected} parameter widgets visible"
                )

                # ============================================================
                # TEST 3: Close some widgets
                # ============================================================
                print("\n--- Test 3: Close Widgets ---")

                # Disable half the widgets
                all_keys = list(app.parameter_flags.keys())
                for key in all_keys[: len(all_keys) // 2]:
                    app.parameter_flags[key].set(False)

                app._render_parameter_widgets()
                visible_count = len(app.widgets)
                assert_true(
                    visible_count < len(PARAMETERS),
                    f"Widgets reduced after closing ({visible_count} < {len(PARAMETERS)})"
                )

                # Re-enable all for more tests
                for key in all_keys:
                    app.parameter_flags[key].set(True)
                app._render_parameter_widgets()

                # ============================================================
                # TEST 4: Change widget values
                # ============================================================
                print("\n--- Test 4: Change Widget Values ---")

                # Test DHW Target (first parameter) - number mode
                dhw_widget = find_widget_by_key(app, "dhw_target")
                assert_true(dhw_widget is not None, "DHW Target widget exists")

                if dhw_widget:
                    # Get initial value
                    initial_val = dhw_widget.get_value()
                    print(f"  DHW Target initial: {initial_val}")

                    # Click + button
                    dhw_widget.up_btn.invoke()
                    new_val = dhw_widget.get_value()
                    assert_true(
                        new_val > initial_val,
                        f"+ button increased value ({initial_val} -> {new_val})"
                    )

                    # Click - button
                    dhw_widget.down_btn.invoke()
                    after_minus = dhw_widget.get_value()
                    assert_true(
                        abs(after_minus - initial_val) < 0.01,
                        f"- button returned to initial ({after_minus} ~= {initial_val})"
                    )

                    # Type a value in entry
                    dhw_widget.entry_var.set("50")
                    dhw_widget.set_btn.invoke()
                    assert_equal(dhw_widget.get_value(), 50.0, "Entry set to 50")

                # ============================================================
                # TEST 5: Change widget modes
                # ============================================================
                print("\n--- Test 5: Change Widget Modes ---")

                outlet_widget = find_widget_by_key(app, "outlet_target")
                assert_true(outlet_widget is not None, "Outlet Target widget exists")

                if outlet_widget:
                    # Switch to slider mode
                    outlet_widget.set_mode("slider")
                    assert_equal(outlet_widget.get_mode(), "slider", "Mode changed to slider")
                    assert_true(hasattr(outlet_widget, "slider"), "Slider control exists")
                    assert_true(outlet_widget.slider.winfo_exists(), "Slider widget exists")

                    # Switch to dial mode
                    outlet_widget.set_mode("dial")
                    assert_equal(outlet_widget.get_mode(), "dial", "Mode changed to dial")
                    assert_true(hasattr(outlet_widget, "dial"), "Dial control exists")
                    assert_true(outlet_widget.dial.winfo_exists(), "Dial widget exists")

                    # Switch back to number mode
                    outlet_widget.set_mode("number")
                    assert_equal(outlet_widget.get_mode(), "number", "Mode changed back to number")

                # ============================================================
                # TEST 6: Drag widget (simulate with canvas move)
                # ============================================================
                print("\n--- Test 6: Drag Widgets ---")

                outdoor_widget = find_widget_by_key(app, "outdoor_temp")
                assert_true(outdoor_widget is not None, "Outdoor Temp widget exists")

                if outdoor_widget:
                    pair = app.widgets["outdoor_temp"]
                    window_id = pair[1]

                    # Get initial position
                    initial_coords = app.canvas.coords(window_id)
                    print(f"  Initial coords: {initial_coords}")

                    # Simulate drag by moving the canvas window
                    app.canvas.move(window_id, 100, 80)
                    new_coords = app.canvas.coords(window_id)
                    print(f"  After drag coords: {new_coords}")

                    assert_true(
                        abs(new_coords[0] - initial_coords[0] - 100) < 1,
                        "Widget moved 100px right"
                    )
                    assert_true(
                        abs(new_coords[1] - initial_coords[1] - 80) < 1,
                        "Widget moved 80px down"
                    )

                    # Save position to config
                    app.config_data.setdefault("widget_positions", {})["outdoor_temp"] = {
                        "x": int(new_coords[0]),
                        "y": int(new_coords[1]),
                    }

                # ============================================================
                # TEST 7: Open relay widgets
                # ============================================================
                print("\n--- Test 7: Relay Widgets ---")

                for relay_key in app.relay_flags:
                    app.relay_flags[relay_key].set(True)

                app._render_relay_widgets()
                assert_equal(
                    len(app.relay_widgets),
                    len(RELAYS),
                    f"All {len(RELAYS)} relay widgets visible"
                )

                # Toggle a relay
                boiler_relay = find_relay_widget(app, "boiler_contact")
                if boiler_relay:
                    initial_state = boiler_relay.get_state()
                    boiler_relay._toggle()
                    new_state = boiler_relay.get_state()
                    assert_true(
                        new_state != initial_state,
                        f"Relay toggled ({initial_state} -> {new_state})"
                    )
                    # Toggle back
                    boiler_relay._toggle()

                # ============================================================
                # TEST 8: Save Named Layout
                # ============================================================
                print("\n--- Test 8: Save Named Layout ---")

                layout = app._capture_current_layout()
                assert_true(isinstance(layout, dict), "Layout captured as dict")
                assert_true("visible_parameters" in layout, "Layout has visible_parameters")
                assert_true("widget_positions" in layout, "Layout has widget_positions")
                assert_true("widget_modes" in layout, "Layout has widget_modes")

                app.config_data.setdefault("named_layouts", {})["test_layout"] = layout
                app._refresh_layout_menus()

                assert_true(
                    "test_layout" in app.config_data["named_layouts"],
                    "Named layout saved"
                )

                # ============================================================
                # TEST 9: Load Named Layout
                # ============================================================
                print("\n--- Test 9: Load Named Layout ---")

                # First, change something to make it different
                for key in list(app.parameter_flags.keys())[:2]:
                    app.parameter_flags[key].set(False)
                app._render_parameter_widgets()
                count_after_close = len(app.widgets)

                # Now load the saved layout
                saved = app.config_data["named_layouts"]["test_layout"]
                app._apply_layout(saved, rerender=True)
                count_after_load = len(app.widgets)

                assert_true(
                    count_after_load > count_after_close,
                    f"Layout restored more widgets ({count_after_load} > {count_after_close})"
                )

                # ============================================================
                # TEST 10: Save config to disk
                # ============================================================
                print("\n--- Test 10: Save Config to Disk ---")

                app._save_config()
                assert_true(CONFIG_FILE.exists(), "Config file created")

                loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                assert_true(isinstance(loaded, dict), "Config file is valid JSON")
                assert_true("visible_parameters" in loaded, "Config has visible_parameters")
                assert_true("named_layouts" in loaded, "Config has named_layouts")
                assert_true("widget_modes" in loaded, "Config has widget_modes")
                assert_true("widget_positions" in loaded, "Config has widget_positions")
                assert_true("latest_layout" in loaded, "Config has latest_layout")

                # Verify named layout persisted
                assert_true(
                    "test_layout" in loaded.get("named_layouts", {}),
                    "Named layout persisted in config file"
                )

                # ============================================================
                # TEST 11: Test widget resize
                # ============================================================
                print("\n--- Test 11: Widget Resize ---")

                dhw = find_widget_by_key(app, "dhw_target")
                if dhw:
                    initial_w = dhw.winfo_width()
                    # Simulate resize by configuring
                    dhw.configure(width=300, height=250)
                    app.update_idletasks()

                    # Fire resize callback directly
                    app._on_widget_resize("dhw_target", 300, 250)
                    saved_size = app.config_data.get("widget_sizes", {}).get("dhw_target")
                    assert_true(saved_size is not None, "Resize saved to config")
                    if saved_size:
                        assert_equal(saved_size["width"], 300, "Width saved as 300")
                        assert_equal(saved_size["height"], 250, "Height saved as 250")

                # ============================================================
                # TEST 12: Test layout delete
                # ============================================================
                print("\n--- Test 12: Delete Named Layout ---")

                assert_true(
                    "test_layout" in app.config_data.get("named_layouts", {}),
                    "Layout exists before delete"
                )

                del app.config_data["named_layouts"]["test_layout"]
                app._refresh_layout_menus()

                assert_true(
                    "test_layout" not in app.config_data["named_layouts"],
                    "Layout deleted from config"
                )

                # ============================================================
                # TEST 13: Test all widget modes for all parameter widgets
                # ============================================================
                print("\n--- Test 13: Cycle All Widget Modes ---")

                for key, (widget, _) in app.widgets.items():
                    for mode in ("number", "slider", "dial"):
                        widget.set_mode(mode)
                        assert_equal(
                            widget.get_mode(), mode,
                            f"{key} mode changed to {mode}"
                        )

                # ============================================================
                # TEST 14: Restore fresh state from default layout
                # ============================================================
                print("\n--- Test 14: Default Layout Restore ---")

                default = app._default_layout()
                app._apply_layout(default, rerender=True)
                assert_equal(
                    len(app.widgets),
                    len(DEFAULT_VISIBLE_PARAMETERS),
                    "Default layout restored"
                )

                # ============================================================
                # TEST 15: Foreground / Z-Order on Click
                # ============================================================
                print("\n--- Test 15: Foreground / Z-Order on Click ---")

                # Re-enable all parameter widgets for overlap testing
                for key in app.parameter_flags:
                    app.parameter_flags[key].set(True)
                app._render_parameter_widgets()
                app.update_idletasks()

                # Verify initial z-order matches creation order
                assert_equal(
                    len(app.widget_z_order),
                    len(PARAMETERS),
                    f"All {len(PARAMETERS)} widgets in z-order"
                )

                # ------------------------------------------------------------
                # 15a: Click first widget - it should move to end of z-order
                # ------------------------------------------------------------
                print("\n  -- 15a: Click moves widget to front --")

                first_key = app.widget_z_order[0]
                app._bring_widget_to_front(first_key)
                assert_equal(
                    app.widget_z_order[-1],
                    first_key,
                    f"Clicked widget '{first_key}' is last in z-order"
                )
                assert_true(
                    app.widget_z_order[0] != first_key,
                    f"Clicked widget '{first_key}' no longer at front of z-order"
                )

                # ------------------------------------------------------------
                # 15b: Click second widget, verify order after multiple clicks
                # ------------------------------------------------------------
                print("\n  -- 15b: Multiple clicks maintain correct order --")

                second_key = app.widget_z_order[0]  # new first after above
                app._bring_widget_to_front(second_key)
                assert_equal(
                    app.widget_z_order[-1],
                    second_key,
                    f"Second clicked widget '{second_key}' is last in z-order"
                )
                # first_key should now be second-to-last
                assert_equal(
                    app.widget_z_order[-2],
                    first_key,
                    f"First clicked widget '{first_key}' is second-to-last"
                )

                # ------------------------------------------------------------
                # 15c: Clicking the already-front widget is a no-op
                # ------------------------------------------------------------
                print("\n  -- 15c: Clicking frontmost widget is stable --")

                z_before = list(app.widget_z_order)
                app._bring_widget_to_front(app.widget_z_order[-1])
                assert_equal(
                    app.widget_z_order,
                    z_before,
                    "Clicking frontmost widget does not change z-order"
                )

                # ------------------------------------------------------------
                # 15d: Overlap widgets by position, then click through z-order
                # ------------------------------------------------------------
                print("\n  -- 15d: Overlapped widgets click-to-front --")

                # Position three widgets at the same spot to create overlap
                keys_to_overlap = list(app.widgets.keys())[:3]
                for k in keys_to_overlap:
                    pair = app.widgets[k]
                    window_id = pair[1]
                    app.canvas.coords(window_id, 50, 50)

                # Click them in reverse order; verify each becomes last
                for expected_last in keys_to_overlap:
                    app._bring_widget_to_front(expected_last)
                    assert_equal(
                        app.widget_z_order[-1],
                        expected_last,
                        f"Overlapped widget '{expected_last}' brought to front"
                    )

                # All three overlapped keys should be the last 3 in z-order
                last_three = app.widget_z_order[-3:]
                assert_equal(
                    set(last_three),
                    set(keys_to_overlap),
                    "All three overlapped widgets occupy the last 3 z-order slots"
                )

                # ------------------------------------------------------------
                # 15e: Drag start brings widget to front
                # ------------------------------------------------------------
                print("\n  -- 15e: Drag brings widget to front --")

                # Pick a widget that's NOT last
                drag_key = app.widget_z_order[1]  # middle widget
                pair = app.widgets[drag_key]
                widget, window_id = pair

                # Simulate drag start via the header ButtonPress-1 binding
                # This triggers _bring_widget_to_front via the drag start handler
                widget.header.event_generate("<ButtonPress-1>", x=10, y=10)
                app.update_idletasks()

                assert_equal(
                    app.widget_z_order[-1],
                    drag_key,
                    f"Dragged widget '{drag_key}' moved to front of z-order"
                )

                # ------------------------------------------------------------
                # 15f: Widget resize brings it to front
                # ------------------------------------------------------------
                print("\n  -- 15f: Resize brings widget to front --")

                resize_key = app.widget_z_order[0]  # pick current first
                pair = app.widgets[resize_key]
                resize_widget, resize_wid = pair

                app._on_widget_resize(resize_key, 280, 240)

                assert_equal(
                    app.widget_z_order[-1],
                    resize_key,
                    f"Resized widget '{resize_key}' moved to front of z-order"
                )

                # ------------------------------------------------------------
                # 15g: Unknown key is silently ignored
                # ------------------------------------------------------------
                print("\n  -- 15g: Unknown key does not crash --")

                z_before = list(app.widget_z_order)
                app._bring_widget_to_front("nonexistent_key")
                assert_equal(
                    app.widget_z_order,
                    z_before,
                    "Bringing nonexistent key to front is a safe no-op"
                )

                # ------------------------------------------------------------
                # 15h: Mode switch preserves click-to-front binding
                # ------------------------------------------------------------
                print("\n  -- 15h: Mode switch re-binds foreground clicks --")

                mode_key = app.widget_z_order[0]
                mode_pair = app.widgets[mode_key]
                mode_widget = mode_pair[0]

                # Switch mode - this should re-bind click handlers via _on_mode_changed
                mode_widget.set_mode("slider")
                app.update_idletasks()
                # The after_idle from _on_mode_changed needs to run
                app.update()

                # Now click should still work
                app._bring_widget_to_front(mode_key)
                assert_equal(
                    app.widget_z_order[-1],
                    mode_key,
                    f"After mode switch, clicking '{mode_key}' still brings to front"
                )

                # Restore number mode
                mode_widget.set_mode("number")
                app.update_idletasks()
                app.update()

                # ------------------------------------------------------------
                # 15i: Z-order is rebuilt on re-render (creation order)
                # ------------------------------------------------------------
                print("\n  -- 15i: Z-order rebuilt on re-render --")

                # Pick a widget that is NOT the last parameter in PARAMETERS
                # so we can verify re-render resets its position.
                # dhw_target is the first PARAMETER; we bring it to front,
                # then re-render should put it back at the beginning.
                reorder_key = "dhw_target"
                assert_true(
                    reorder_key in app.widgets,
                    f"'{reorder_key}' widget is visible"
                )

                # Verify it's NOT already last, then bring it to front
                assert_true(
                    app.widget_z_order[-1] != reorder_key or len(app.widget_z_order) == 1,
                    f"'{reorder_key}' is not last before bring-to-front"
                )
                app._bring_widget_to_front(reorder_key)
                assert_equal(
                    app.widget_z_order[-1],
                    reorder_key,
                    f"'{reorder_key}' moved to front"
                )

                # Re-render rebuilds z_order from scratch based on visible flags
                app._render_parameter_widgets()
                # After re-render, all widgets should be back in creation order
                assert_equal(
                    len(app.widget_z_order),
                    len(PARAMETERS),
                    "After re-render, z-order still has all widgets"
                )
                # dhw_target is the first PARAMETER, so it should be first
                # in creation order after re-render (NOT last)
                assert_equal(
                    app.widget_z_order[0],
                    reorder_key,
                    f"After re-render, '{reorder_key}' is first in creation order"
                )

                # ------------------------------------------------------------
                # 15i-2: Clicking a child element brings widget to front
                # ------------------------------------------------------------
                print("\n  -- 15i-2: Clicking child element brings to front --")

                child_test_key = app.widget_z_order[0]
                child_pair = app.widgets[child_test_key]
                child_widget = child_pair[0]

                # Click the + button (a child of the widget) and verify
                # the foreground binding fires and brings widget to front
                child_widget.up_btn.event_generate("<ButtonPress-1>", x=5, y=5)
                app.update_idletasks()

                assert_equal(
                    app.widget_z_order[-1],
                    child_test_key,
                    f"Clicking child button of '{child_test_key}' brings widget to front"
                )

                # ------------------------------------------------------------
                # 15j: Relay widget click-to-front via direct method
                # ------------------------------------------------------------
                print("\n  -- 15j: Relay widget click-to-front --")

                for relay_key in app.relay_flags:
                    app.relay_flags[relay_key].set(True)
                app._render_relay_widgets()
                app.update_idletasks()

                assert_true(
                    len(app.relay_z_order) == len(RELAYS),
                    f"All {len(RELAYS)} relay widgets in relay z-order"
                )

                # Bring first relay to front
                first_relay = app.relay_z_order[0]
                app._bring_relay_to_front(first_relay)
                assert_equal(
                    app.relay_z_order[-1],
                    first_relay,
                    f"Relay '{first_relay}' moved to front of relay z-order"
                )

                # 15j-2: Relay drag start also brings to front (via direct call)
                relay_drag_key = app.relay_z_order[0]
                app._bring_relay_to_front(relay_drag_key)
                assert_equal(
                    app.relay_z_order[-1],
                    relay_drag_key,
                    f"Relay '{relay_drag_key}' brought to front via direct call"
                )

                # 15j-3: Relay resize brings to front
                resize_relay_key = app.relay_z_order[0]
                app._on_relay_resize(resize_relay_key, 260, 180)
                assert_equal(
                    app.relay_z_order[-1],
                    resize_relay_key,
                    f"Resized relay '{resize_relay_key}' moved to front"
                )

                # 15j-4: Relay foreground click on child element
                # (this tests the _bring_widget_to_front dispatcher fix)
                print("\n  -- 15j-4: Relay foreground click on child --")

                relay_click_key = app.relay_z_order[0]
                relay_pair = app.relay_widgets[relay_click_key]
                rwidget, _ = relay_pair
                # Click the toggle button (a child of the relay widget)
                rwidget.toggle_btn.event_generate("<ButtonPress-1>", x=5, y=5)
                app.update_idletasks()
                assert_equal(
                    app.relay_z_order[-1],
                    relay_click_key,
                    f"Clicking relay child button brings '{relay_click_key}' to front"
                )

                # ------------------------------------------------------------
                # 15k: CZ-TAW1 relay z-order
                # ------------------------------------------------------------
                print("\n  -- 15k: CZ-TAW1 relay z-order --")

                from heishasim.models import CZTAW1_RELAYS

                # Enable CZ-TAW1 addon mode and relays to render them
                app.config_data["addon_enabled"] = True
                app.state_engine.set_model(app.config_data.get("model", "H/J Generic"))
                for relay_key in app.cz_taw1_relay_flags:
                    app.cz_taw1_relay_flags[relay_key].set(True)
                app.cz_taw1_sensor_flag.set(True)
                app._render_cz_taw1_widgets()
                app.update_idletasks()

                # Verify z-order has CZ-TAW1 relays
                expected_cz_count = len(CZTAW1_RELAYS)
                assert_true(
                    len(app.cz_taw1_relay_z_order) == expected_cz_count,
                    f"All {expected_cz_count} CZ-TAW1 relay widgets in z-order"
                )

                # Verify sensor widget exists (it's not tracked in cz_taw1_relay_z_order)
                assert_true(
                    app.cz_taw1_sensor_widget is not None,
                    "CZ-TAW1 external sensor widget exists"
                )

                # 15k-1: Bring first CZ-TAW1 relay to front
                if app.cz_taw1_relay_z_order:
                    first_cz = app.cz_taw1_relay_z_order[0]
                    app._bring_cz_taw1_relay_to_front(first_cz)
                    assert_equal(
                        app.cz_taw1_relay_z_order[-1],
                        first_cz,
                        f"CZ-TAW1 relay '{first_cz}' moved to front"
                    )

                # 15k-2: CZ-TAW1 relay resize brings to front
                if app.cz_taw1_relay_z_order:
                    resize_cz_key = app.cz_taw1_relay_z_order[0]
                    app._on_cz_taw1_relay_resize(resize_cz_key, 260, 180)
                    assert_equal(
                        app.cz_taw1_relay_z_order[-1],
                        resize_cz_key,
                        f"Resized CZ-TAW1 relay '{resize_cz_key}' moved to front"
                    )

                # 15k-3: Unknown CZ-TAW1 key is safe no-op
                cz_before = list(app.cz_taw1_relay_z_order)
                app._bring_cz_taw1_relay_to_front("nonexistent_cz_key")
                assert_equal(
                    app.cz_taw1_relay_z_order,
                    cz_before,
                    "Bringing unknown CZ-TAW1 key to front is a safe no-op"
                )

                # 15k-4: CZ-TAW1 foreground click on child element
                # (verifies _bring_widget_to_front dispatches to _bring_cz_taw1_relay_to_front)
                if app.cz_taw1_relay_widgets:
                    print("\n  -- 15k-4: CZ-TAW1 foreground click on child --")
                    cz_click_key = app.cz_taw1_relay_z_order[0]
                    cz_pair = app.cz_taw1_relay_widgets[cz_click_key]
                    cz_w, _ = cz_pair
                    # Click the toggle button (a child of the CZ-TAW1 relay widget)
                    cz_w.toggle_btn.event_generate("<ButtonPress-1>", x=5, y=5)
                    app.update_idletasks()
                    assert_equal(
                        app.cz_taw1_relay_z_order[-1],
                        cz_click_key,
                        f"Clicking CZ-TAW1 relay child button brings '{cz_click_key}' to front"
                    )

                # Disable addon mode to clean up
                app.config_data["addon_enabled"] = False
                app._render_cz_taw1_widgets()

                # ============================================================
                # ALL TESTS COMPLETE
                # ============================================================
                print("\n" + "="*60)
                print("ALL TESTS COMPLETE")
                print("="*60)

            except Exception as e:
                import traceback
                traceback.print_exc()
                results.fail(f"Test crashed: {e}")
            finally:
                # Clean up
                app._closing = True
                try:
                    app.after_cancel(app._log_after_id)
                except Exception:
                    pass
                app._log_after_id = None
                app.destroy()

        # Run tests after a short delay to let UI initialize
        app.after(500, run_all_tests)

        # Auto-close after tests (30 second max)
        app.after(30000, lambda: app.destroy())

        app.mainloop()

    finally:
        # Restore config backup
        if config_backup is not None:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(config_backup, encoding="utf-8")
        elif CONFIG_FILE.exists():
            CONFIG_FILE.unlink()

    return results.summary()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
