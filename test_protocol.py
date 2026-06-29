"""Unit tests for heishasim.protocol — checksum, frame building, value encoding, HeatPumpState."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from heishasim.models import (
    CZTAW1_EXTERNAL_SENSOR,
    CZTAW1_RELAYS,
    MODEL_SIGNATURES,
    PARAMETERS,
    RELAYS,
)
from heishasim.protocol import (
    HeatPumpState,
    _encode_value,
    append_checksum,
    build_query,
    build_startup_query,
    calc_checksum,
    is_valid_frame,
)


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
        print(f"Protocol tests: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            for e in self.errors:
                print(f"  FAIL: {e}")
        print(f"{'='*60}")
        return self.failed == 0


results = TestResults()


def assert_equal(a, b, msg: str):
    if a == b:
        results.ok(f"{msg} (got {a!r})")
    else:
        results.fail(f"{msg}: expected {b!r}, got {a!r}")


def assert_true(cond, msg: str):
    if cond:
        results.ok(msg)
    else:
        results.fail(msg)


# ---------------------------------------------------------------------------
# calc_checksum
# ---------------------------------------------------------------------------

def test_calc_checksum():
    print("\n--- calc_checksum ---")

    # A known hand-computable case: [0x71, 0xC8] = sum=0x139, &0xFF=0x39,
    # ^0xFF=0xC6, +1=0xC7, &0xFF=0xC7
    assert_equal(calc_checksum(bytes([0x71, 0xC8])), 0xC7, "Checksum of [0x71, 0xC8]")

    # Empty input: total=0, (0^0xFF)+1 = 0x100 & 0xFF = 0x00
    assert_equal(calc_checksum(b""), 0x00, "Checksum of empty bytes")

    # Single byte 0x00: total=0, checksum=0x00
    assert_equal(calc_checksum(b"\x00"), 0x00, "Checksum of [0x00]")

    # Single byte 0xFF: total=0xFF, (0xFF^0xFF)+1 = 1, &0xFF = 1
    assert_equal(calc_checksum(b"\xff"), 0x01, "Checksum of [0xFF]")

    # Frame that sums to exactly 0x100 (256): truncated to 0, checksum 0
    # 0x80 + 0x80 = 0x100 -> &0xFF = 0 -> checksum = 0
    assert_equal(calc_checksum(bytes([0x80, 0x80])), 0x00, "Checksum when sum=0x100")


# ---------------------------------------------------------------------------
# append_checksum
# ---------------------------------------------------------------------------

def test_append_checksum():
    print("\n--- append_checksum ---")

    data = bytes([0x71, 0xC8])
    result = append_checksum(data)
    assert_equal(len(result), 3, "append_checksum adds one byte")
    assert_equal(result[-1], calc_checksum(data), "Appended byte equals checksum")
    # Full frame validity: sum of all bytes & 0xFF == 0
    assert_equal(sum(result) & 0xFF, 0, "Full frame sum & 0xFF == 0")


# ---------------------------------------------------------------------------
# is_valid_frame
# ---------------------------------------------------------------------------

def test_is_valid_frame():
    print("\n--- is_valid_frame ---")

    # Construct a valid frame
    data = bytes([0x71, 0xC8, 0x01, 0x10])
    valid = append_checksum(data)
    assert_true(is_valid_frame(valid), "Valid frame passes is_valid_frame")

    # Corrupt the frame
    corrupted = bytearray(valid)
    corrupted[0] = 0x72
    assert_true(not is_valid_frame(bytes(corrupted)), "Corrupted frame fails is_valid_frame")

    # All-zero: sum=0, valid
    assert_true(is_valid_frame(bytes(10)), "All-zero frame is valid (sum=0)")

    # Single byte that doesn't zero out
    assert_true(not is_valid_frame(bytes([0x01])), "Single [0x01] fails validation")


# ---------------------------------------------------------------------------
# build_query
# ---------------------------------------------------------------------------

def test_build_query():
    print("\n--- build_query ---")

    # Default query (block_type=0x10, header=0x71)
    q = build_query()
    assert_equal(q[0], 0x71, "Default query starts with 0x71")
    assert_equal(q[1], 0x6C, "Second byte is 0x6C")
    assert_equal(q[2], 0x01, "Third byte is 0x01")
    assert_equal(q[3], 0x10, "Fourth byte is block_type 0x10")
    assert_equal(len(q), 111, "Default query is 111 bytes (110 payload + 1 checksum)")
    assert_true(is_valid_frame(q), "Default query passes validation")

    # Extra block query
    q21 = build_query(block_type=0x21)
    assert_equal(q21[3], 0x21, "Extra query has block_type 0x21")
    assert_true(is_valid_frame(q21), "Extra query passes validation")

    # Custom header
    q31 = build_query(header=0x31)
    assert_equal(q31[0], 0x31, "Custom header 0x31")
    assert_true(is_valid_frame(q31), "Custom header query passes validation")


# ---------------------------------------------------------------------------
# build_startup_query
# ---------------------------------------------------------------------------

def test_build_startup_query():
    print("\n--- build_startup_query ---")

    sq = build_startup_query()
    assert_equal(sq[0], 0x31, "Startup query starts with 0x31")
    assert_equal(sq[1], 0x05, "Second byte is 0x05")
    assert_equal(sq[2], 0x10, "Third byte is 0x10")
    assert_equal(sq[3], 0x01, "Fourth byte is 0x01")
    assert_equal(len(sq), 8, "Startup query is 8 bytes (7 payload + 1 checksum)")
    assert_true(is_valid_frame(sq), "Startup query passes validation")


# ---------------------------------------------------------------------------
# _encode_value
# ---------------------------------------------------------------------------

def test_encode_value():
    print("\n--- _encode_value ---")

    # offset_128: value + 128, clamped 0..255
    assert_equal(_encode_value(0, "offset_128"), 128, "offset_128(0) = 128")
    assert_equal(_encode_value(49, "offset_128"), 177, "offset_128(49) = 177")
    assert_equal(_encode_value(-128, "offset_128"), 0, "offset_128(-128) = 0 (floor)")
    assert_equal(_encode_value(127, "offset_128"), 255, "offset_128(127) = 255 (ceiling)")
    assert_equal(_encode_value(-150, "offset_128"), 0, "offset_128(-150) clamped to 0")
    assert_equal(_encode_value(200, "offset_128"), 255, "offset_128(200) clamped to 255")

    # minus_one: value + 1, clamped 0..255
    assert_equal(_encode_value(0, "minus_one"), 1, "minus_one(0) = 1")
    assert_equal(_encode_value(40, "minus_one"), 41, "minus_one(40) = 41")
    assert_equal(_encode_value(-1, "minus_one"), 0, "minus_one(-1) = 0")
    assert_equal(_encode_value(254, "minus_one"), 255, "minus_one(254) = 255")
    assert_equal(_encode_value(260, "minus_one"), 255, "minus_one(260) clamped to 255")

    # raw: direct, clamped 0..255
    assert_equal(_encode_value(42, "raw"), 42, "raw(42) = 42")
    assert_equal(_encode_value(0, "raw"), 0, "raw(0) = 0")
    assert_equal(_encode_value(255, "raw"), 255, "raw(255) = 255")
    assert_equal(_encode_value(-5, "raw"), 0, "raw(-5) clamped to 0")
    assert_equal(_encode_value(300, "raw"), 255, "raw(300) clamped to 255")

    # Rounding
    assert_equal(_encode_value(48.6, "offset_128"), 177, "offset_128(48.6) rounds to 177")
    assert_equal(_encode_value(48.4, "offset_128"), 176, "offset_128(48.4) rounds to 176")
    assert_equal(_encode_value(0.6, "minus_one"), 2, "minus_one(0.6) rounds to 2")


# ---------------------------------------------------------------------------
# HeatPumpState — basic state management
# ---------------------------------------------------------------------------

def test_heatpump_state_defaults():
    print("\n--- HeatPumpState defaults ---")

    state = HeatPumpState()
    assert_equal(state.model_name, "H/J Generic", "Default model is H/J Generic")
    assert_true(state.supports_extra_block, "Default supports_extra_block is True")

    for param in PARAMETERS:
        val = state.get_value(param.key)
        assert_equal(val, param.default, f"Default value for {param.key}")

    for relay in RELAYS:
        val = state.get_relay_state(relay.key)
        assert_equal(val, relay.default, f"Default relay state for {relay.key}")

    for relay in CZTAW1_RELAYS:
        val = state.get_cz_taw1_relay_state(relay.key)
        assert_equal(val, relay.default, f"Default CZ-TAW1 relay state for {relay.key}")

    temp = state.get_cz_taw1_external_sensor_temp()
    assert_equal(temp, CZTAW1_EXTERNAL_SENSOR.default, "Default CZ-TAW1 external sensor temp")


def test_heatpump_state_set_get_values():
    print("\n--- HeatPumpState set/get ---")

    state = HeatPumpState()

    # Set and get a parameter
    state.set_value("dhw_target", 55)
    assert_equal(state.get_value("dhw_target"), 55, "Set/get dhw_target=55")

    # Clamp to minimum
    state.set_value("dhw_target", 10)
    assert_equal(state.get_value("dhw_target"), 35, "dhw_target clamped to min=35")

    # Clamp to maximum
    state.set_value("dhw_target", 100)
    assert_equal(state.get_value("dhw_target"), 60, "dhw_target clamped to max=60")

    # Unknown key is ignored
    state.set_value("nonexistent", 99)
    assert_equal(state.get_value("nonexistent"), 0.0, "Unknown key returns 0.0")

    # Relay set/get
    state.set_relay_state("boiler_contact", True)
    assert_true(state.get_relay_state("boiler_contact"), "boiler_contact set to True")

    state.set_relay_state("boiler_contact", False)
    assert_true(not state.get_relay_state("boiler_contact"), "boiler_contact set to False")

    # Relay toggle
    state.toggle_relay("external_control")
    assert_true(state.get_relay_state("external_control"), "external_control toggled to True")
    state.toggle_relay("external_control")
    assert_true(not state.get_relay_state("external_control"), "external_control toggled back to False")

    # Unknown relay ignored
    state.set_relay_state("fake_relay", True)
    assert_true(not state.get_relay_state("fake_relay"), "Unknown relay returns False")

    # CZ-TAW1 relay
    state.set_cz_taw1_relay_state("relay_one", True)
    assert_true(state.get_cz_taw1_relay_state("relay_one"), "CZ-TAW1 relay_one set to True")

    # CZ-TAW1 external sensor
    state.set_cz_taw1_external_sensor_temp(25.5)
    assert_equal(state.get_cz_taw1_external_sensor_temp(), 25.5, "CZ-TAW1 sensor temp set to 25.5")

    # Clamp CZ-TAW1 sensor
    state.set_cz_taw1_external_sensor_temp(-100)
    assert_equal(
        state.get_cz_taw1_external_sensor_temp(),
        CZTAW1_EXTERNAL_SENSOR.minimum,
        f"CZ-TAW1 sensor clamped to min={CZTAW1_EXTERNAL_SENSOR.minimum}",
    )

    state.set_cz_taw1_external_sensor_temp(200)
    assert_equal(
        state.get_cz_taw1_external_sensor_temp(),
        CZTAW1_EXTERNAL_SENSOR.maximum,
        f"CZ-TAW1 sensor clamped to max={CZTAW1_EXTERNAL_SENSOR.maximum}",
    )


def test_heatpump_state_set_model():
    print("\n--- HeatPumpState set_model ---")

    state = HeatPumpState()
    state.set_model("K-Series Generic")
    assert_equal(state.model_name, "K-Series Generic", "Model changed to K-Series")

    state.set_model("L-Series Generic")
    assert_equal(state.model_name, "L-Series Generic", "Model changed to L-Series")

    # Unknown model is ignored
    state.set_model("Fake Model")
    assert_equal(state.model_name, "L-Series Generic", "Unknown model ignored")


# ---------------------------------------------------------------------------
# HeatPumpState — frame building
# ---------------------------------------------------------------------------

def test_build_main_response():
    print("\n--- HeatPumpState.build_main_response ---")

    state = HeatPumpState()

    frame = state.build_main_response()
    assert_true(isinstance(frame, bytes), "Main response is bytes")
    assert_equal(len(frame), 203, "Main response is 203 bytes (202 payload + 1 checksum)")
    assert_equal(frame[0], 0x71, "Header byte 0x71")
    assert_equal(frame[1], 0xC8, "Length byte 0xC8")
    assert_equal(frame[2], 0x01, "Sequence byte 0x01")
    assert_equal(frame[3], 0x10, "Block type 0x10 (main)")
    assert_true(is_valid_frame(frame), "Main response frame is valid (checksum correct)")

    # Model signature at bytes 129-138
    sig = MODEL_SIGNATURES["H/J Generic"]
    for i, expected_byte in enumerate(sig):
        assert_equal(frame[129 + i], expected_byte, f"Signature byte {i} for H/J Generic")

    # Check specific parameter encodings
    # DHW Target default=49, offset_128 -> 177
    assert_equal(frame[42], 177, "DHW Target (default 49) encoded at byte 42")
    # Compressor freq default=40, minus_one -> 41
    assert_equal(frame[166], 41, "Compressor freq (default 40) encoded at byte 166")
    # Water pressure default=1.5, raw -> 2 (rounded)
    assert_equal(frame[125], 2, "Water pressure (default 1.5) encoded at byte 125")

    # Relay defaults (False -> 0)
    assert_equal(frame[176], 0, "Boiler contact default False -> 0")
    assert_equal(frame[177], 0, "External control default False -> 0")

    # Extra block indicator at byte 199
    assert_equal(frame[199], 0x03, "supports_extra_block=True -> byte 199 = 0x03")

    # Known fixed bytes
    assert_equal(frame[110], 0x55, "Byte 110 = 0x55")
    assert_equal(frame[111], 0x56, "Byte 111 = 0x56")
    assert_equal(frame[112], 0x55, "Byte 112 = 0x55")
    assert_equal(frame[120], 0x19, "Byte 120 = 0x19")
    assert_equal(frame[191], 0x06, "Byte 191 = 0x06")


def test_build_main_response_reflects_changes():
    print("\n--- Main response reflects state changes ---")

    state = HeatPumpState()

    # Change a value and verify it appears in the frame
    state.set_value("dhw_target", 60)
    frame = state.build_main_response()
    # 60 + 128 = 188
    assert_equal(frame[42], 188, "dhw_target=60 encoded as 188 at byte 42")

    # Change a relay
    state.set_relay_state("boiler_contact", True)
    frame = state.build_main_response()
    assert_equal(frame[176], 1, "boiler_contact=True -> byte 176 = 1")

    # Change model signature
    state.set_model("K-Series Generic")
    frame = state.build_main_response()
    sig = MODEL_SIGNATURES["K-Series Generic"]
    for i, expected_byte in enumerate(sig):
        assert_equal(frame[129 + i], expected_byte, f"K-Series signature byte {i}")

    # Verify frame is still valid after all changes
    assert_true(is_valid_frame(frame), "Frame valid after state changes")


def test_build_main_response_no_extra_block():
    print("\n--- Main response with supports_extra_block=False ---")

    state = HeatPumpState()
    state.supports_extra_block = False
    frame = state.build_main_response()
    assert_equal(frame[199], 0x00, "supports_extra_block=False -> byte 199 = 0x00")
    assert_true(is_valid_frame(frame), "Frame valid without extra block")


def test_build_main_response_cz_taw1_sensor():
    print("\n--- Main response with CZ-TAW1 external sensor ---")

    state = HeatPumpState()
    state.set_cz_taw1_external_sensor_temp(20)
    frame = state.build_main_response()
    # 20 + 128 = 148
    assert_equal(frame[CZTAW1_EXTERNAL_SENSOR.byte_index], 148, "CZ-TAW1 sensor 20degC -> 148")
    assert_true(is_valid_frame(frame), "Frame valid with CZ-TAW1 sensor")


def test_build_extra_response():
    print("\n--- HeatPumpState.build_extra_response ---")

    state = HeatPumpState()

    frame = state.build_extra_response()
    assert_true(isinstance(frame, bytes), "Extra response is bytes")
    assert_equal(len(frame), 203, "Extra response is 203 bytes")
    assert_equal(frame[0], 0x71, "Header byte 0x71")
    assert_equal(frame[3], 0x21, "Block type 0x21 (extra)")
    assert_true(is_valid_frame(frame), "Extra response frame is valid")

    # Default compressor freq = 40, power_heat = 40 * 50 = 2000
    # Byte 14 = 2000 & 0xFF = 0xD0 = 208, Byte 15 = (2000 >> 8) & 0xFF = 0x07 = 7
    assert_equal(frame[14], 2000 & 0xFF, "Power heat low byte (compressor_freq=40)")
    assert_equal(frame[15], (2000 >> 8) & 0xFF, "Power heat high byte")

    # Default outlet_temp = 48, generated_heat = 48 * 100 = 4800
    assert_equal(frame[20], 4800 & 0xFF, "Generated heat low byte (outlet_temp=48)")
    assert_equal(frame[21], (4800 >> 8) & 0xFF, "Generated heat high byte")


def test_build_extra_response_reflects_changes():
    print("\n--- Extra response reflects state changes ---")

    state = HeatPumpState()
    state.set_value("compressor_freq", 80)
    state.set_value("outlet_temp", 55)

    frame = state.build_extra_response()
    power_heat = 80 * 50  # 4000
    generated_heat = int(55 * 100)  # 5500

    assert_equal(frame[14], power_heat & 0xFF, "Updated power heat low byte")
    assert_equal(frame[15], (power_heat >> 8) & 0xFF, "Updated power heat high byte")
    assert_equal(frame[20], generated_heat & 0xFF, "Updated generated heat low byte")
    assert_equal(frame[21], (generated_heat >> 8) & 0xFF, "Updated generated heat high byte")
    assert_true(is_valid_frame(frame), "Extra response valid after changes")


# ---------------------------------------------------------------------------
# HeatPumpState — CZ-TAW1 relay state in main response
# ---------------------------------------------------------------------------

def test_cz_taw1_relays_in_state():
    print("\n--- CZ-TAW1 relay state tracking ---")

    state = HeatPumpState()

    # CZ-TAW1 relays are tracked in state but NOT written into the
    # main response frame (build_main_response only iterates RELAYS,
    # not CZTAW1_RELAYS). Verify the state API works correctly.
    state.set_cz_taw1_relay_state("relay_one", True)
    assert_true(state.get_cz_taw1_relay_state("relay_one"), "relay_one state is True")
    assert_true(not state.get_cz_taw1_relay_state("relay_two"), "relay_two state is False (default)")

    state.set_cz_taw1_relay_state("relay_two", True)
    assert_true(state.get_cz_taw1_relay_state("relay_two"), "relay_two state is True")

    # Main response frame should still be valid
    frame = state.build_main_response()
    assert_true(is_valid_frame(frame), "Frame valid with CZ-TAW1 relay changes")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_calc_checksum()
    test_append_checksum()
    test_is_valid_frame()
    test_build_query()
    test_build_startup_query()
    test_encode_value()
    test_heatpump_state_defaults()
    test_heatpump_state_set_get_values()
    test_heatpump_state_set_model()
    test_build_main_response()
    test_build_main_response_reflects_changes()
    test_build_main_response_no_extra_block()
    test_build_main_response_cz_taw1_sensor()
    test_build_extra_response()
    test_build_extra_response_reflects_changes()
    test_cz_taw1_relays_in_state()

    success = results.summary()
    sys.exit(0 if success else 1)
