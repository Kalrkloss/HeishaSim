from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .protocol import build_query, build_startup_query, is_valid_frame

try:
    import serial
    from serial.tools import list_ports
except Exception:  # pragma: no cover - optional dependency guard
    serial = None
    list_ports = None


StatusCallback = Callable[[str], None]
FrameCallback = Callable[[str], None]


def available_serial_ports() -> list[str]:
    if list_ports is None:
        return []
    return [port.device for port in list_ports.comports()]


@dataclass
class SerialSettings:
    port: str
    baudrate: int = 9600


class HeatPumpSerialServer(threading.Thread):
    def __init__(
        self,
        settings: SerialSettings,
        state,
        on_status: StatusCallback,
        on_frame: FrameCallback,
    ) -> None:
        super().__init__(daemon=True)
        self.settings = settings
        self.state = state
        self.on_status = on_status
        self.on_frame = on_frame
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        if serial is None:
            self.on_status("pyserial is not installed. Install requirements first.")
            return

        try:
            with serial.Serial(
                port=self.settings.port,
                baudrate=self.settings.baudrate,
                timeout=0.1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE,
            ) as ser:
                self.on_status(f"Heat pump simulator active on {self.settings.port}")
                while not self._stop_event.is_set():
                    frame = self._read_frame(ser)
                    if not frame:
                        continue
                    self.on_frame(f"RX {self.settings.port}: {frame.hex(' ')}")

                    if not is_valid_frame(frame):
                        self.on_frame(f"RX checksum invalid on {self.settings.port}")
                        continue

                    response = self._build_response(frame)
                    if response:
                        ser.write(response)
                        self.on_frame(f"TX {self.settings.port}: {response.hex(' ')}")
        except Exception as exc:
            self.on_status(f"Serial error on {self.settings.port}: {exc}")

    def _read_frame(self, ser) -> bytes | None:
        first = ser.read(1)
        if not first:
            return None

        header = first[0]
        if header not in (0x31, 0x71, 0xF1):
            return None

        length_byte = ser.read(1)
        if not length_byte:
            return None

        length = length_byte[0]
        total = length + 3
        remaining = total - 2
        payload = ser.read(remaining)
        if len(payload) != remaining:
            return None
        return bytes([header, length]) + payload

    def _build_response(self, frame: bytes) -> bytes | None:
        header = frame[0]
        command = frame[3] if len(frame) > 3 else 0x10

        if header == 0x31:
            return self.state.build_main_response()

        if header in (0x71, 0xF1):
            if command == 0x21 and self.state.supports_extra_block:
                return self.state.build_extra_response()
            return self.state.build_main_response()

        return None


class CZTAW1AddonSimulator(threading.Thread):
    def __init__(
        self,
        settings: SerialSettings,
        on_status: StatusCallback,
        on_frame: FrameCallback,
        interval_seconds: float = 2.0,
        send_extra_query: bool = True,
    ) -> None:
        super().__init__(daemon=True)
        self.settings = settings
        self.on_status = on_status
        self.on_frame = on_frame
        self.interval_seconds = interval_seconds
        self.send_extra_query = send_extra_query
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        if serial is None:
            self.on_status("pyserial is not installed. Install requirements first.")
            return

        try:
            with serial.Serial(
                port=self.settings.port,
                baudrate=self.settings.baudrate,
                timeout=0.1,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_ONE,
            ) as ser:
                self.on_status(f"CZ-TAW1 simulator active on {self.settings.port}")
                startup = build_startup_query()
                ser.write(startup)
                self.on_frame(f"TX {self.settings.port}: {startup.hex(' ')}")

                counter = 0
                while not self._stop_event.is_set():
                    query = build_query(0x10, 0x71)
                    ser.write(query)
                    self.on_frame(f"TX {self.settings.port}: {query.hex(' ')}")
                    self._drain_responses(ser)

                    if self.send_extra_query and counter % 3 == 0:
                        query_extra = build_query(0x21, 0x71)
                        ser.write(query_extra)
                        self.on_frame(f"TX {self.settings.port}: {query_extra.hex(' ')}")
                        self._drain_responses(ser)

                    counter += 1
                    if self._stop_event.wait(self.interval_seconds):
                        break
        except Exception as exc:
            self.on_status(f"Serial error on addon port {self.settings.port}: {exc}")

    def _drain_responses(self, ser) -> None:
        # Read available response chunks without blocking long periods.
        time_limit = time.time() + 0.5
        while time.time() < time_limit:
            data = ser.read(256)
            if not data:
                return
            self.on_frame(f"RX {self.settings.port}: {data.hex(' ')}")
