# HeishaSim

HeishaSim is a platform-independent Python GUI simulator for Panasonic Aquarea heat pump serial traffic.
It can emulate a heat pump response stream for tools like HeishaMon and can optionally simulate a CZ-TAW1 addon on a second serial port.

## Features

- Python application (Windows + Linux)
- GUI with top menu bar
- Config menu:
  - Select serial port for heat pump output
  - Select heat pump model
  - Enable CZ-TAW1 simulation on second serial port
- Parameters menu to choose which heat pump parameters are shown on main screen
- Parameter widgets:
  - Large numeric display
  - Up/down buttons
  - Direct value entry
  - Alternative display mode: number, slider, dial
- Relay widgets:
  - Show simulator relay state
  - Toggle relay state directly from the canvas
- Drag and arrange widgets freely on the canvas
- Serial protocol behavior aligned with HeishaMon expectations:
  - Header and length fields
  - checksum rule `sum(all bytes) & 0xFF == 0`
  - basic (`0x10`) and extra (`0x21`) response blocks

## Protocol Notes

- UART settings: `9600`, `8E1`
- Typical query headers supported: `0x31`, `0x71`, `0xF1`
- Main response: `0x71 0xC8 0x01 0x10 ... checksum`
- Extra response: `0x71 0xC8 0x01 0x21 ... checksum`
- Relay state is exposed in reserved main-response bytes `176-179` for simulator tooling.

## Project Structure

- `main.py` entry point
- `heishasim/app.py` GUI and app orchestration
- `heishasim/protocol.py` frame building and heat pump state model
- `heishasim/serial_worker.py` serial server and CZ-TAW1 simulator workers
- `heishasim/widgets.py` parameter widgets (number, slider, dial)
- `heishasim/models.py` parameter definitions and model signatures

## Setup

1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Usage

1. Open `Config -> Serial / Model Settings`.
2. Select the heat pump serial port and model.
3. Optionally enable CZ-TAW1 simulator and choose second serial port.
4. In `Parameters`, select which parameters appear on the main screen.
5. Drag widgets by their header bars.
6. For each widget, use the mode selector (`number`, `slider`, `dial`) as needed.
7. Start simulation from `File -> Start Simulator`.

## Serial Loopback/Test Idea

For local tests, create virtual serial pairs:

- Linux: `socat`
- Windows: com0com or similar virtual COM pair tool

Attach HeishaMon side to one end and HeishaSim to the matching paired port.

## Git Ready

Included:

- `.gitignore`
- `requirements.txt`
- source code and README

Initialize and push:

```bash
git init
git add .
git commit -m "Initial HeishaSim simulator"
```

## Limitations

- This is a practical simulator for development/testing and does not implement every Panasonic command variation.
- Parameter byte mappings are focused on commonly used values and can be extended easily in `heishasim/models.py`.
