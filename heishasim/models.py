from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DisplayMode = Literal["number", "slider", "dial"]


@dataclass(frozen=True)
class ParameterDefinition:
    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    step: float
    default: float
    byte_index: int
    encoding: Literal["offset_128", "minus_one", "raw"] = "offset_128"


@dataclass(frozen=True)
class RelayDefinition:
    key: str
    label: str
    byte_index: int
    default: bool = False


MODEL_SIGNATURES: dict[str, list[int]] = {
    "H/J Generic": [0xE2, 0xCE, 0x0D, 0x71, 0x81, 0x72, 0xCE, 0x0C, 0x92, 0x81],
    "K-Series Generic": [0xE2, 0xCD, 0x0D, 0x71, 0x81, 0x72, 0xCE, 0x0C, 0x92, 0x81],
    "L-Series Generic": [0xE2, 0xCC, 0x0D, 0x71, 0x81, 0x72, 0xCE, 0x0C, 0x92, 0x81],
}


PARAMETERS: list[ParameterDefinition] = [
    ParameterDefinition("dhw_target", "DHW Target", "degC", 35, 60, 1, 49, 42),
    ParameterDefinition("dhw_actual", "DHW Actual", "degC", 20, 65, 0.5, 42, 141),
    ParameterDefinition("outdoor_temp", "Outdoor Temp", "degC", -25, 40, 0.5, 5, 142),
    ParameterDefinition("inlet_temp", "Inlet Temp", "degC", 10, 60, 0.5, 43, 143),
    ParameterDefinition("outlet_temp", "Outlet Temp", "degC", 10, 65, 0.5, 48, 144),
    ParameterDefinition("outlet_target", "Outlet Target", "degC", 20, 65, 0.5, 55, 153),
    ParameterDefinition("compressor_freq", "Compressor Freq", "Hz", 0, 120, 1, 40, 166, "minus_one"),
    ParameterDefinition("pump_duty", "Pump Duty", "pct", 0, 100, 1, 60, 172, "minus_one"),
    ParameterDefinition("heatpump_state", "Heatpump State", "", 0, 1, 1, 1, 4, "raw"),
    ParameterDefinition("operating_mode", "Operating Mode", "", 0, 5, 1, 1, 6, "raw"),
    ParameterDefinition("water_pressure", "Water Pressure", "bar", 0, 4, 0.1, 1.5, 125, "raw"),
    ParameterDefinition("z1_water_temp", "Z1 Water Temp", "degC", 5, 60, 0.5, 35, 145),
    ParameterDefinition("z2_water_temp", "Z2 Water Temp", "degC", 5, 60, 0.5, 25, 146),
    ParameterDefinition("z1_water_target", "Z1 Water Target", "degC", 20, 60, 0.5, 40, 147),
    ParameterDefinition("z2_water_target", "Z2 Water Target", "degC", 20, 60, 0.5, 25, 148),
    ParameterDefinition("discharge_temp", "Discharge Temp", "degC", 0, 130, 1, 60, 155),
    ParameterDefinition("room_thermostat", "Room Thermostat", "degC", 10, 40, 0.5, 22, 156),
    ParameterDefinition("ipm_temp", "IPM Temp", "degC", 0, 100, 1, 40, 162),
    ParameterDefinition("compressor_current", "Compressor Current", "A", 0, 25, 0.5, 5, 165, "raw"),
    ParameterDefinition("fan1_speed", "Fan1 Speed", "rpm", 0, 1000, 10, 400, 173, "raw"),
]


RELAYS: list[RelayDefinition] = [
    RelayDefinition("boiler_contact", "Boiler Contact", 176),
    RelayDefinition("external_control", "External Control", 177),
]


CZTAW1_RELAYS: list[RelayDefinition] = [
    RelayDefinition("relay_one", "Relay One", 180),
    RelayDefinition("relay_two", "Relay Two", 181),
]


CZTAW1_EXTERNAL_SENSOR = ParameterDefinition(
    "cz_taw1_external_sensor",
    "External Sensor Temp",
    "degC",
    -30,
    60,
    0.5,
    20,
    200,
)


PARAMETER_BY_KEY: dict[str, ParameterDefinition] = {p.key: p for p in PARAMETERS}
RELAY_BY_KEY: dict[str, RelayDefinition] = {r.key: r for r in RELAYS}
CZTAW1_RELAY_BY_KEY: dict[str, RelayDefinition] = {r.key: r for r in CZTAW1_RELAYS}
