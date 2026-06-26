from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from .models import (
    CZTAW1_EXTERNAL_SENSOR,
    CZTAW1_RELAY_BY_KEY,
    CZTAW1_RELAYS,
    MODEL_SIGNATURES,
    PARAMETER_BY_KEY,
    PARAMETERS,
    RELAY_BY_KEY,
    RELAYS,
)


def calc_checksum(frame_without_checksum: bytes | bytearray) -> int:
    total = sum(frame_without_checksum) & 0xFF
    return ((total ^ 0xFF) + 1) & 0xFF


def append_checksum(frame_without_checksum: bytes | bytearray) -> bytes:
    chk = calc_checksum(frame_without_checksum)
    return bytes(frame_without_checksum) + bytes([chk])


def is_valid_frame(frame: bytes) -> bool:
    return (sum(frame) & 0xFF) == 0


def build_query(block_type: int = 0x10, header: int = 0x71) -> bytes:
    payload = bytearray([header, 0x6C, 0x01, block_type])
    payload.extend([0x00] * (110 - len(payload)))
    return append_checksum(payload)


def build_startup_query() -> bytes:
    payload = bytearray([0x31, 0x05, 0x10, 0x01, 0x00, 0x00, 0x00])
    return append_checksum(payload)


def _encode_value(value: float, encoding: str) -> int:
    if encoding == "offset_128":
        return max(0, min(255, int(round(value + 128))))
    if encoding == "minus_one":
        return max(0, min(255, int(round(value + 1))))
    return max(0, min(255, int(round(value))))


@dataclass
class HeatPumpState:
    model_name: str = "H/J Generic"
    values: dict[str, float] = field(default_factory=dict)
    relay_values: dict[str, bool] = field(default_factory=dict)
    cz_taw1_relay_values: dict[str, bool] = field(default_factory=dict)
    cz_taw1_external_sensor_temp: float = CZTAW1_EXTERNAL_SENSOR.default
    supports_extra_block: bool = True
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.values:
            self.values = {p.key: p.default for p in PARAMETERS}
        if not self.relay_values:
            self.relay_values = {r.key: r.default for r in RELAYS}
        if not self.cz_taw1_relay_values:
            self.cz_taw1_relay_values = {r.key: r.default for r in CZTAW1_RELAYS}

    def set_model(self, model_name: str) -> None:
        if model_name not in MODEL_SIGNATURES:
            return
        with self._lock:
            self.model_name = model_name

    def set_value(self, key: str, value: float) -> None:
        param = PARAMETER_BY_KEY.get(key)
        if param is None:
            return
        with self._lock:
            self.values[key] = max(param.minimum, min(param.maximum, value))

    def get_value(self, key: str) -> float:
        with self._lock:
            return self.values.get(key, 0.0)

    def set_relay_state(self, key: str, enabled: bool) -> None:
        relay = RELAY_BY_KEY.get(key)
        if relay is None:
            return
        with self._lock:
            self.relay_values[key] = bool(enabled)

    def get_relay_state(self, key: str) -> bool:
        with self._lock:
            return bool(self.relay_values.get(key, False))

    def toggle_relay(self, key: str) -> None:
        with self._lock:
            self.relay_values[key] = not bool(self.relay_values.get(key, False))

    def set_cz_taw1_relay_state(self, key: str, enabled: bool) -> None:
        relay = CZTAW1_RELAY_BY_KEY.get(key)
        if relay is None:
            return
        with self._lock:
            self.cz_taw1_relay_values[key] = bool(enabled)

    def get_cz_taw1_relay_state(self, key: str) -> bool:
        with self._lock:
            return bool(self.cz_taw1_relay_values.get(key, False))

    def set_cz_taw1_external_sensor_temp(self, value: float) -> None:
        with self._lock:
            self.cz_taw1_external_sensor_temp = max(
                CZTAW1_EXTERNAL_SENSOR.minimum,
                min(CZTAW1_EXTERNAL_SENSOR.maximum, value),
            )

    def get_cz_taw1_external_sensor_temp(self) -> float:
        with self._lock:
            return self.cz_taw1_external_sensor_temp

    def build_main_response(self) -> bytes:
        with self._lock:
            frame = bytearray([0x71, 0xC8, 0x01, 0x10])
            frame.extend([0x00] * (202 - len(frame)))

            for param in PARAMETERS:
                raw = _encode_value(self.values.get(param.key, param.default), param.encoding)
                frame[param.byte_index] = raw

            for relay in RELAYS:
                frame[relay.byte_index] = 1 if self.relay_values.get(relay.key, relay.default) else 0

            frame[CZTAW1_EXTERNAL_SENSOR.byte_index] = max(
                0,
                min(255, int(round(self.cz_taw1_external_sensor_temp + 128))),
            )

            signature = MODEL_SIGNATURES.get(self.model_name, MODEL_SIGNATURES["H/J Generic"])
            for i, value in enumerate(signature):
                frame[129 + i] = value

            frame[110] = 0x55
            frame[111] = 0x56
            frame[112] = 0x55
            frame[120] = 0x19
            frame[191] = 0x06
            frame[192] = 0x02 if "T-CAP" in self.model_name else 0x01
            frame[199] = 0x03 if self.supports_extra_block else 0x00

            return append_checksum(frame)

    def build_extra_response(self) -> bytes:
        with self._lock:
            frame = bytearray([0x71, 0xC8, 0x01, 0x21])
            frame.extend([0x00] * (202 - len(frame)))

            compressor = self.values.get("compressor_freq", 0)
            outlet = self.values.get("outlet_temp", 0)
            power_heat = int(max(0, compressor * 50))
            generated_heat = int(max(0, outlet * 100))

            frame[14] = power_heat & 0xFF
            frame[15] = (power_heat >> 8) & 0xFF
            frame[20] = generated_heat & 0xFF
            frame[21] = (generated_heat >> 8) & 0xFF

            return append_checksum(frame)
