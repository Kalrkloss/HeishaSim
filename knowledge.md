# HeishaSim — Project Knowledge

## What This Is

A Python GUI simulator for Panasonic Aquarea heat pump serial traffic. It emulates heat pump responses over serial for tools like HeishaMon and optionally simulates a CZ-TAW1 addon on a second serial port. Built with **tkinter** for the GUI and **pyserial** for serial communication.

## Key Files

| File | Purpose |
|---|---|
| `main.py` | Entry point — just calls `heishasim.app.main()` |
| `heishasim/app.py` | GUI orchestration (`HeishaSimApp` extends `tk.Tk`), config dialog, layout management, serial start/stop |
| `heishasim/models.py` | Data models: `ParameterDefinition`, `RelayDefinition`, `MODEL_SIGNATURES`, `PARAMETERS`, `RELAYS`, `CZTAW1_RELAYS` |
| `heishasim/protocol.py` | Frame building, checksum logic, `HeatPumpState` (thread-safe state engine) |
| `heishasim/serial_worker.py` | `HeatPumpSerialServer` and `CZTAW1AddonSimulator` background threads |
| `heishasim/widgets.py` | `ParameterWidget`, `BinaryWidget`, `RelayWidget`, `AddonRelayWidget` — all tkinter `Frame` subclasses |
| `test_heishasim.py` | Automated UI tests exercising widgets, dragging, z-order, layouts, close buttons |

## Commands

```bash
# Install dependencies (virtual env recommended)
pip install -r requirements.txt

# Run the app
python main.py

# Run tests
python test_heishasim.py
```

**Note:** `tkinter` cannot be pip-installed. On Linux: `sudo apt install python3-tk`. On Windows/macOS it ships with Python.

## Architecture & Conventions

- **Python ≥3.10** required (uses `from __future__ import annotations`, `dict[str, ...]` syntax).
- **Thread safety:** `HeatPumpState` uses a `threading.Lock` for all reads/writes since serial workers run on background threads.
- **Config persistence:** JSON file at `~/.heishasim/heishasim_config.json` (managed via `CONFIG_FILE` in `app.py`). Stores widget positions, sizes, modes, layouts, relay states.
- **Serial protocol:** 9600 baud, 8E1. Checksum rule: `sum(all bytes) & 0xFF == 0`. Main response header `0x10`, extra response header `0x21`.
- **Widget types:**
  - Parameters with `min=0, max=1, step=1` render as `BinaryWidget` (on/off toggle).
  - All others render as `ParameterWidget` with three display modes: `number`, `slider`, `dial`.
  - Relays use `RelayWidget`; CZ-TAW1 relays use `AddonRelayWidget`.
- **Z-order management:** Three separate z-order lists (`widget_z_order`, `relay_z_order`, `cz_taw1_relay_z_order`). Click-to-front uses `canvas.tag_raise()` for cross-type stacking.
- **Widget dragging:** Bound via `<ButtonPress-1>`, `<B1-Motion>`, `<ButtonRelease-1>` on the header bar. Positions saved to config on drop.
- **Close buttons:** Each widget type has a close button (`×`) in its header. Uses `bindtags` reordering so the close button's click doesn't bubble to the drag handler.
- **Layout system:** Named layouts stored in config. Startup behavior can be "latest" or "default".

## Gotchas

- Tests (`test_heishasim.py`) use `sys.path.insert` to find the package — the test file expects to live adjacent to the `heishasim/` directory.
- The test file backs up and restores `CONFIG_FILE` around test runs; tests delete any existing config first.
- `app.dragging["item"]` must be `None` before close-button tests or drag state bleeds into assertions.
- CZ-TAW1 widgets only render when `config_data["addon_enabled"]` is `True`.
- The `CZTAW1_EXTERNAL_SENSOR` key is appended to `cz_taw1_relay_z_order` (not a separate list), so its z-order count = `len(CZTAW1_RELAYS) + 1`.
- Parameter byte encodings: `offset_128` (value + 128), `minus_one` (value + 1), `raw` (direct). Defined per-parameter in `models.py`.
- On Windows, virtual serial port pairs (for loopback testing) require tools like com0com; on Linux use `socat`.
