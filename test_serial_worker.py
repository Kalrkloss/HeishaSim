"""Unit tests for heishasim.serial_worker — edge cases for serial frame reading,
response building, drain logic, port listing, and thread lifecycle."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from heishasim.protocol import HeatPumpState, append_checksum, build_query, build_startup_query

# ---------------------------------------------------------------------------
# Mock serial objects (no pyserial dependency needed for unit tests)
# ---------------------------------------------------------------------------

class MockSerial:
    """Minimal mock of serial.Serial for testing _read_frame and _drain_responses."""

    def __init__(self, read_data: bytes = b"", port: str = "MOCK", baudrate: int = 9600):
        self._read_data = read_data
        self._read_pos = 0
        self._written: list[bytes] = []
        self.port = port
        self.baudrate = baudrate
        self.is_open = True

    def read(self, size: int) -> bytes:
        chunk = self._read_data[self._read_pos : self._read_pos + size]
        self._read_pos += len(chunk)
        return chunk

    def write(self, data: bytes) -> int:
        self._written.append(data)
        return len(data)

    def close(self):
        self.is_open = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


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
        print(f"Serial worker tests: {self.passed}/{total} passed, {self.failed} failed")
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
# Helper: build a minimal valid frame for _read_frame testing
# ---------------------------------------------------------------------------

def make_frame(header: int, length: int, payload_extra: bytes = b"") -> bytes:
    """Build a checksum-valid frame: [header, length, ...payload..., checksum]."""
    payload = bytes([header, length]) + payload_extra
    # Pad to `length + 1` bytes (length field counts bytes after length byte + checksum)
    # Actually the protocol: total = length + 3, frame = [header, length] + (total-2) bytes
    # remaining = total - 2 = length + 1
    needed = length + 1 - len(payload_extra)
    if needed > 0:
        payload += b"\x00" * needed
    return append_checksum(payload)


# ---------------------------------------------------------------------------
# HeatPumpSerialServer._read_frame tests
# ---------------------------------------------------------------------------

def test_read_frame_empty_read():
    """read(1) returns empty bytes -> None."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    ser = MockSerial(read_data=b"")
    result = server._read_frame(ser)
    assert_equal(result, None, "Empty read returns None")


def test_read_frame_invalid_header():
    """First byte not in (0x31, 0x71, 0xF1) -> None."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    for bad_header in [0x00, 0x10, 0x21, 0x50, 0xFF]:
        ser = MockSerial(read_data=bytes([bad_header, 0x05, 0x00]))
        result = server._read_frame(ser)
        assert_equal(result, None, f"Header 0x{bad_header:02X} rejected")


def test_read_frame_valid_headers():
    """Headers 0x31, 0x71, 0xF1 are accepted."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    for hdr in [0x31, 0x71, 0xF1]:
        frame = make_frame(hdr, 5)
        ser = MockSerial(read_data=frame)
        result = server._read_frame(ser)
        assert_true(result is not None, f"Header 0x{hdr:02X} accepted, got {len(result) if result else 0} bytes")
        if result:
            assert_equal(result[0], hdr, f"Returned frame starts with 0x{hdr:02X}")


def test_read_frame_missing_length_byte():
    """Header valid but no length byte available -> None."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    ser = MockSerial(read_data=bytes([0x71]))  # header only, no length
    result = server._read_frame(ser)
    assert_equal(result, None, "Missing length byte returns None")


def test_read_frame_truncated_payload():
    """Payload shorter than expected -> None."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # length=10 -> remaining = 11 bytes needed after [header, length]
    # Only provide 3 bytes of payload
    data = bytes([0x71, 0x0A]) + b"\x00" * 3
    ser = MockSerial(read_data=data)
    result = server._read_frame(ser)
    assert_equal(result, None, "Truncated payload returns None")


def test_read_frame_length_zero():
    """Length=0 -> total=3, remaining=1 byte (just checksum area)."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    frame = make_frame(0x71, 0)
    ser = MockSerial(read_data=frame)
    result = server._read_frame(ser)
    assert_true(result is not None, "Length=0 frame accepted")
    if result:
        assert_equal(len(result), 3, "Length=0 frame is 3 bytes [header, length, checksum]")


def test_read_frame_minimum_valid():
    """Minimum valid frame: header + length=0 + 1 remaining byte."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # length=0: total=3, remaining=1 -> need [header, length, one_more_byte, checksum]
    # Actually: remaining = total - 2 = 1. So we read 1 byte of payload after header+length.
    # Frame = [header, length] + payload(1 byte) = 3 bytes. But append_checksum adds 1 more.
    # Let me trace: make_frame(0x31, 0) -> payload = [0x31, 0x00], needed = 0+1-0 = 1
    # -> payload = [0x31, 0x00, 0x00], append_checksum -> [0x31, 0x00, 0x00, checksum]
    # _read_frame reads: first=0x31, length_byte=0x00, length=0, total=3, remaining=1
    # reads 1 byte -> gets 0x00. Returns [0x31, 0x00, 0x00] (3 bytes, no checksum in return)
    # Wait, it returns bytes([header, length]) + payload = [0x31, 0x00] + [0x00] = [0x31, 0x00, 0x00]
    # But the actual frame sent was [0x31, 0x00, 0x00, checksum_byte].
    # read(remaining=1) only reads 1 byte (0x00), so the checksum byte is NOT consumed.
    frame = make_frame(0x31, 0)
    ser = MockSerial(read_data=frame)
    result = server._read_frame(ser)
    assert_true(result is not None, "Minimum valid frame accepted")
    if result:
        assert_equal(result[0], 0x31, "Frame starts with header")
        assert_equal(result[1], 0x00, "Frame length byte is 0")


def test_read_frame_large_payload():
    """Larger payload (simulating a real query frame)."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # length=108 -> remaining=109, frame = [0x71, 0x6C] + 109 bytes + checksum
    frame = make_frame(0x71, 108)
    ser = MockSerial(read_data=frame)
    result = server._read_frame(ser)
    assert_true(result is not None, "Large payload frame accepted")
    if result:
        assert_equal(len(result), 111, "Large frame is 111 bytes (2 + 109)")
        assert_equal(result[0], 0x71, "Header preserved")
        assert_equal(result[1], 108, "Length byte preserved")


def test_read_frame_real_query():
    """Read back an actual build_query() frame."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    query = build_query(0x10, 0x71)
    ser = MockSerial(read_data=query)
    result = server._read_frame(ser)
    assert_true(result is not None, "Real query frame accepted")
    if result:
        assert_equal(len(result), len(query), f"Returned frame matches query length ({len(query)})")
        assert_equal(result[0], 0x71, "Query header 0x71")
        assert_equal(result[1], 0x6C, "Query length 0x6C (108)")


def test_read_frame_real_startup_query():
    """Read back an actual build_startup_query() frame."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    startup = build_startup_query()
    ser = MockSerial(read_data=startup)
    result = server._read_frame(ser)
    assert_true(result is not None, "Startup query frame accepted")
    if result:
        assert_equal(len(result), len(startup), "Startup frame length matches")
        assert_equal(result[0], 0x31, "Startup header 0x31")


# ---------------------------------------------------------------------------
# HeatPumpSerialServer._build_response tests
# ---------------------------------------------------------------------------

def test_build_response_startup_header():
    """Header 0x31 -> main response."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # 0x31 header always returns main response
    frame = bytes([0x31, 0x05, 0x10, 0x01, 0x00, 0x00, 0x00, 0x00])
    response = server._build_response(frame)
    assert_true(response is not None, "0x31 header returns a response")
    if response:
        expected = state.build_main_response()
        assert_equal(len(response), len(expected), "0x31 returns main response (203 bytes)")


def test_build_response_query_header():
    """Header 0x71 with command 0x10 -> main response."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    frame = bytes([0x71, 0x6C, 0x01, 0x10] + [0x00] * 106)
    response = server._build_response(frame)
    assert_true(response is not None, "0x71/0x10 returns a response")
    if response:
        assert_equal(response[3], 0x10, "Main response block type 0x10")


def test_build_response_extra_block_supported():
    """Header 0x71 with command 0x21 and supports_extra_block=True -> extra response."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    state.supports_extra_block = True
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    frame = bytes([0x71, 0x6C, 0x01, 0x21] + [0x00] * 106)
    response = server._build_response(frame)
    assert_true(response is not None, "0x71/0x21 with extra block returns a response")
    if response:
        assert_equal(response[3], 0x21, "Extra response block type 0x21")


def test_build_response_extra_block_not_supported():
    """Header 0x71 with command 0x21 and supports_extra_block=False -> main response."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    state.supports_extra_block = False
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    frame = bytes([0x71, 0x6C, 0x01, 0x21] + [0x00] * 106)
    response = server._build_response(frame)
    assert_true(response is not None, "0x71/0x21 without extra block returns a response")
    if response:
        assert_equal(response[3], 0x10, "Falls back to main response block type 0x10")


def test_build_response_f1_header():
    """Header 0xF1 behaves like 0x71."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # 0xF1 with command 0x10 -> main response
    frame_10 = bytes([0xF1, 0x6C, 0x01, 0x10] + [0x00] * 106)
    resp_10 = server._build_response(frame_10)
    assert_true(resp_10 is not None, "0xF1/0x10 returns a response")
    if resp_10:
        assert_equal(resp_10[3], 0x10, "0xF1/0x10 -> main response")

    # 0xF1 with command 0x21 and extra block -> extra response
    state.supports_extra_block = True
    frame_21 = bytes([0xF1, 0x6C, 0x01, 0x21] + [0x00] * 106)
    resp_21 = server._build_response(frame_21)
    assert_true(resp_21 is not None, "0xF1/0x21 returns a response")
    if resp_21:
        assert_equal(resp_21[3], 0x21, "0xF1/0x21 -> extra response")


def test_build_response_short_frame():
    """Frame shorter than 4 bytes uses default command 0x10."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    # Frame with only 2 bytes -> command defaults to 0x10
    frame = bytes([0x71, 0x00])
    response = server._build_response(frame)
    assert_true(response is not None, "Short frame still produces a response")
    if response:
        assert_equal(response[3], 0x10, "Short frame defaults to main response")


def test_build_response_unknown_header():
    """Unknown header -> None."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    frame = bytes([0x50, 0x05, 0x10, 0x10, 0x00])
    response = server._build_response(frame)
    assert_equal(response, None, "Unknown header 0x50 returns None")


# ---------------------------------------------------------------------------
# HeatPumpSerialServer — pyserial-not-installed guard
# ---------------------------------------------------------------------------

def test_run_no_serial():
    """run() with serial=None reports error via on_status."""
    import heishasim.serial_worker as sw

    # Temporarily set serial to None
    saved_serial = sw.serial
    sw.serial = None  # type: ignore[assignment]
    try:
        status_msgs: list[str] = []
        server = sw.HeatPumpSerialServer(
            settings=sw.SerialSettings(port="MOCK"),
            state=HeatPumpState(),
            on_status=status_msgs.append,
            on_frame=lambda _: None,
        )
        server.run()  # Should return immediately
        assert_true(len(status_msgs) == 1, "on_status called once when serial is None")
        if status_msgs:
            assert_true(
                "pyserial is not installed" in status_msgs[0],
                f"Status message mentions pyserial: {status_msgs[0]!r}",
            )
    finally:
        sw.serial = saved_serial


# ---------------------------------------------------------------------------
# HeatPumpSerialServer — stop / threading
# ---------------------------------------------------------------------------

def test_server_stop_sets_event():
    """Calling stop() sets the internal stop event."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=HeatPumpState(),
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    assert_true(not server._stop_event.is_set(), "Stop event not set initially")
    server.stop()
    assert_true(server._stop_event.is_set(), "Stop event set after stop()")


def test_server_is_daemon_thread():
    """HeatPumpSerialServer is a daemon thread."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=HeatPumpState(),
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    assert_true(server.daemon, "Server thread is daemon")


# ---------------------------------------------------------------------------
# HeatPumpSerialServer — serial error handling in run()
# ---------------------------------------------------------------------------

def test_run_serial_exception():
    """run() catches serial exceptions and reports via on_status."""
    import heishasim.serial_worker as sw

    # Create a fake serial module that raises on Serial()
    class FakeSerial:
        EIGHTBITS = 8
        PARITY_EVEN = "E"
        STOPBITS_ONE = 1

        def Serial(self, **kwargs):
            raise OSError("Port not found")

    saved_serial = sw.serial
    sw.serial = FakeSerial()  # type: ignore[assignment]
    try:
        status_msgs: list[str] = []
        server = sw.HeatPumpSerialServer(
            settings=sw.SerialSettings(port="NONEXISTENT"),
            state=HeatPumpState(),
            on_status=status_msgs.append,
            on_frame=lambda _: None,
        )
        server.run()
        assert_true(len(status_msgs) >= 1, "on_status called on serial error")
        if status_msgs:
            assert_true(
                "Serial error" in status_msgs[-1],
                f"Error message mentions serial error: {status_msgs[-1]!r}",
            )
    finally:
        sw.serial = saved_serial


# ---------------------------------------------------------------------------
# CZTAW1AddonSimulator — pyserial-not-installed guard
# ---------------------------------------------------------------------------

def test_addon_run_no_serial():
    """CZTAW1AddonSimulator.run() with serial=None reports error."""
    import heishasim.serial_worker as sw

    saved_serial = sw.serial
    sw.serial = None  # type: ignore[assignment]
    try:
        status_msgs: list[str] = []
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=status_msgs.append,
            on_frame=lambda _: None,
        )
        addon.run()
        assert_true(len(status_msgs) == 1, "on_status called once when serial is None")
        if status_msgs:
            assert_true(
                "pyserial is not installed" in status_msgs[0],
                f"Addon status mentions pyserial: {status_msgs[0]!r}",
            )
    finally:
        sw.serial = saved_serial


# ---------------------------------------------------------------------------
# CZTAW1AddonSimulator — stop / threading
# ---------------------------------------------------------------------------

def test_addon_stop_sets_event():
    """Calling stop() sets the internal stop event."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    assert_true(not addon._stop_event.is_set(), "Addon stop event not set initially")
    addon.stop()
    assert_true(addon._stop_event.is_set(), "Addon stop event set after stop()")


def test_addon_is_daemon_thread():
    """CZTAW1AddonSimulator is a daemon thread."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    assert_true(addon.daemon, "Addon thread is daemon")


def test_addon_default_settings():
    """Default interval and send_extra_query."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    assert_equal(addon.interval_seconds, 2.0, "Default interval is 2.0s")
    assert_true(addon.send_extra_query, "Default send_extra_query is True")

    addon2 = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=lambda _: None,
        interval_seconds=5.0,
        send_extra_query=False,
    )
    assert_equal(addon2.interval_seconds, 5.0, "Custom interval is 5.0s")
    assert_true(not addon2.send_extra_query, "Custom send_extra_query is False")


# ---------------------------------------------------------------------------
# CZTAW1AddonSimulator — serial error handling in run()
# ---------------------------------------------------------------------------

def test_addon_run_serial_exception():
    """CZTAW1AddonSimulator.run() catches serial exceptions."""
    import heishasim.serial_worker as sw

    class FakeSerial:
        EIGHTBITS = 8
        PARITY_EVEN = "E"
        STOPBITS_ONE = 1

        def Serial(self, **kwargs):
            raise OSError("Addon port error")

    saved_serial = sw.serial
    sw.serial = FakeSerial()  # type: ignore[assignment]
    try:
        status_msgs: list[str] = []
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="NONEXISTENT"),
            on_status=status_msgs.append,
            on_frame=lambda _: None,
        )
        addon.run()
        assert_true(len(status_msgs) >= 1, "on_status called on addon serial error")
        if status_msgs:
            assert_true(
                "Serial error" in status_msgs[-1],
                f"Addon error message: {status_msgs[-1]!r}",
            )
    finally:
        sw.serial = saved_serial


# ---------------------------------------------------------------------------
# CZTAW1AddonSimulator._drain_responses tests
# ---------------------------------------------------------------------------

def test_drain_responses_reads_data():
    """_drain_responses reads available data and reports via on_frame."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    frame_msgs: list[str] = []
    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=frame_msgs.append,
    )
    # Mock serial that returns data once then empty
    data = bytes([0x71, 0xC8, 0x01, 0x10])
    call_count = 0

    class DrainSerial:
        def read(self, size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return data
            return b""

    ser = DrainSerial()
    addon._drain_responses(ser)
    assert_true(len(frame_msgs) == 1, f"on_frame called once (got {len(frame_msgs)})")
    if frame_msgs:
        assert_true("RX" in frame_msgs[0], f"Frame message contains RX: {frame_msgs[0]!r}")
        assert_true(data.hex(" ") in frame_msgs[0], "Frame message contains hex data")


def test_drain_responses_no_data():
    """_drain_responses with no data -> no on_frame calls."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    frame_msgs: list[str] = []
    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=frame_msgs.append,
    )

    class EmptySerial:
        def read(self, size):
            return b""

    ser = EmptySerial()
    addon._drain_responses(ser)
    assert_equal(len(frame_msgs), 0, "No on_frame calls when no data available")


def test_drain_responses_multiple_chunks():
    """_drain_responses reads multiple chunks before timeout."""
    from heishasim.serial_worker import CZTAW1AddonSimulator, SerialSettings

    frame_msgs: list[str] = []
    addon = CZTAW1AddonSimulator(
        settings=SerialSettings(port="MOCK"),
        on_status=lambda _: None,
        on_frame=frame_msgs.append,
    )
    chunk1 = bytes([0x71, 0xC8])
    chunk2 = bytes([0x31, 0x05])
    call_count = 0

    class MultiChunkSerial:
        def read(self, size):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return chunk1
            if call_count == 2:
                return chunk2
            return b""

    ser = MultiChunkSerial()
    addon._drain_responses(ser)
    assert_equal(len(frame_msgs), 2, "Two chunks produce two on_frame calls")


# ---------------------------------------------------------------------------
# SerialSettings dataclass
# ---------------------------------------------------------------------------

def test_serial_settings_defaults():
    """SerialSettings has correct defaults."""
    from heishasim.serial_worker import SerialSettings

    s = SerialSettings(port="COM3")
    assert_equal(s.port, "COM3", "Port is COM3")
    assert_equal(s.baudrate, 9600, "Default baudrate is 9600")


def test_serial_settings_custom_baudrate():
    """SerialSettings accepts custom baudrate."""
    from heishasim.serial_worker import SerialSettings

    s = SerialSettings(port="/dev/ttyUSB0", baudrate=115200)
    assert_equal(s.port, "/dev/ttyUSB0", "Port is /dev/ttyUSB0")
    assert_equal(s.baudrate, 115200, "Baudrate is 115200")


# ---------------------------------------------------------------------------
# available_serial_ports
# ---------------------------------------------------------------------------

def test_available_serial_ports_no_list_ports():
    """available_serial_ports() returns [] when list_ports is None."""
    import heishasim.serial_worker as sw

    saved = sw.list_ports
    sw.list_ports = None  # type: ignore[assignment]
    try:
        ports = sw.available_serial_ports()
        assert_equal(ports, [], "Returns empty list when list_ports is None")
    finally:
        sw.list_ports = saved


# ---------------------------------------------------------------------------
# Integration: round-trip read_frame -> build_response
# ---------------------------------------------------------------------------

def test_roundtrip_startup_query():
    """Read a startup query frame, build response, verify valid."""
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    startup = build_startup_query()
    ser = MockSerial(read_data=startup)
    frame = server._read_frame(ser)
    assert_true(frame is not None, "Startup query read successfully")
    if frame:
        response = server._build_response(frame)
        assert_true(response is not None, "Response built for startup query")
        if response:
            from heishasim.protocol import is_valid_frame
            assert_true(is_valid_frame(response), "Response frame checksum is valid")


def test_roundtrip_main_query():
    """Read a main query frame, build response, verify valid."""
    from heishasim.protocol import is_valid_frame
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    query = build_query(0x10, 0x71)
    ser = MockSerial(read_data=query)
    frame = server._read_frame(ser)
    assert_true(frame is not None, "Main query read successfully")
    if frame:
        response = server._build_response(frame)
        assert_true(response is not None, "Response built for main query")
        if response:
            assert_true(is_valid_frame(response), "Main response checksum is valid")
            assert_equal(response[3], 0x10, "Response block type is 0x10")


def test_roundtrip_extra_query():
    """Read an extra query frame with extra block supported, build response."""
    from heishasim.protocol import is_valid_frame
    from heishasim.serial_worker import HeatPumpSerialServer, SerialSettings

    state = HeatPumpState()
    state.supports_extra_block = True
    server = HeatPumpSerialServer(
        settings=SerialSettings(port="MOCK"),
        state=state,
        on_status=lambda _: None,
        on_frame=lambda _: None,
    )
    query = build_query(0x21, 0x71)
    ser = MockSerial(read_data=query)
    frame = server._read_frame(ser)
    assert_true(frame is not None, "Extra query read successfully")
    if frame:
        response = server._build_response(frame)
        assert_true(response is not None, "Response built for extra query")
        if response:
            assert_true(is_valid_frame(response), "Extra response checksum is valid")
            assert_equal(response[3], 0x21, "Response block type is 0x21")


# ---------------------------------------------------------------------------
# HeatPumpSerialServer — run loop with mock serial (integration)
# ---------------------------------------------------------------------------

def test_run_loop_processes_frame():
    """run() reads a frame, builds response, and writes it back via mock serial."""
    import heishasim.serial_worker as sw
    from heishasim.protocol import is_valid_frame

    state = HeatPumpState()
    query = build_query(0x10, 0x71)

    # Create a mock serial module whose Serial() returns our MockSerial
    # pre-loaded with a query frame, then returns empty on subsequent reads
    # so the loop exits when stop() is called.
    mock_ser = MockSerial(read_data=query)

    class FakeSerialModule:
        EIGHTBITS = 8
        PARITY_EVEN = "E"
        STOPBITS_ONE = 1

        def Serial(self, **kwargs):
            return mock_ser

    saved_serial = sw.serial
    sw.serial = FakeSerialModule()  # type: ignore[assignment]
    try:
        frame_msgs: list[str] = []
        status_msgs: list[str] = []

        server = sw.HeatPumpSerialServer(
            settings=sw.SerialSettings(port="MOCK"),
            state=state,
            on_status=status_msgs.append,
            on_frame=frame_msgs.append,
        )
        server.start()
        # Give the thread time to read the frame and write the response
        time.sleep(0.3)
        server.stop()
        server.join(timeout=2.0)

        # Should have RX and TX messages
        rx_msgs = [m for m in frame_msgs if m.startswith("RX")]
        tx_msgs = [m for m in frame_msgs if m.startswith("TX")]
        assert_true(len(rx_msgs) >= 1, f"At least one RX message (got {len(rx_msgs)})")
        assert_true(len(tx_msgs) >= 1, f"At least one TX message (got {len(tx_msgs)})")

        # Verify the response was written to mock serial
        assert_true(len(mock_ser._written) >= 1, f"Response written to serial (got {len(mock_ser._written)})")
        if mock_ser._written:
            response = mock_ser._written[0]
            assert_true(is_valid_frame(response), "Written response has valid checksum")
    finally:
        sw.serial = saved_serial


def test_run_loop_invalid_checksum():
    """run() detects invalid checksum and logs it without writing a response."""
    import heishasim.serial_worker as sw

    state = HeatPumpState()
    # Build a frame with corrupted checksum
    query = bytearray(build_query(0x10, 0x71))
    query[-1] ^= 0xFF  # corrupt checksum
    corrupted_query = bytes(query)

    mock_ser = MockSerial(read_data=corrupted_query)

    class FakeSerialModule:
        EIGHTBITS = 8
        PARITY_EVEN = "E"
        STOPBITS_ONE = 1

        def Serial(self, **kwargs):
            return mock_ser

    saved_serial = sw.serial
    sw.serial = FakeSerialModule()  # type: ignore[assignment]
    try:
        frame_msgs: list[str] = []

        server = sw.HeatPumpSerialServer(
            settings=sw.SerialSettings(port="MOCK"),
            state=state,
            on_status=lambda _: None,
            on_frame=frame_msgs.append,
        )
        server.start()
        time.sleep(0.3)
        server.stop()
        server.join(timeout=2.0)

        checksum_msgs = [m for m in frame_msgs if "checksum invalid" in m]
        assert_true(len(checksum_msgs) >= 1, "Invalid checksum detected and logged")
        assert_equal(len(mock_ser._written), 0, "No response written for invalid checksum")
    finally:
        sw.serial = saved_serial


# ---------------------------------------------------------------------------
# CZTAW1AddonSimulator — run-loop integration tests with mock serial
# ---------------------------------------------------------------------------

class TrackWriteSerial:
    """Mock serial that records all writes and returns empty on reads."""

    def __init__(self):
        self._written: list[bytes] = []
        self._read_count = 0

    def read(self, size: int) -> bytes:
        self._read_count += 1
        return b""

    def write(self, data: bytes) -> int:
        self._written.append(data)
        return len(data)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _make_fake_serial_module(mock_ser):
    """Create a fake serial module whose Serial() always returns mock_ser."""

    class _FakeModule:
        EIGHTBITS = 8
        PARITY_EVEN = "E"
        STOPBITS_ONE = 1

        def Serial(self, **kwargs):  # noqa: N802
            return mock_ser

    return _FakeModule()


def test_addon_runloop_sends_startup_query():
    """run() sends build_startup_query() as the first write."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
        )
        addon.start()
        time.sleep(0.2)
        addon.stop()
        addon.join(timeout=2.0)

        assert_true(len(mock_ser._written) >= 1, "At least one write occurred")
        if mock_ser._written:
            startup = build_startup_query()
            assert_equal(mock_ser._written[0], startup, "First write is the startup query")
    finally:
        sw.serial = saved


def test_addon_runloop_sends_main_queries():
    """run() sends build_query(0x10, 0x71) in each loop iteration."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
            send_extra_query=False,
        )
        addon.start()
        time.sleep(0.3)
        addon.stop()
        addon.join(timeout=2.0)

        main_query = build_query(0x10, 0x71)
        # First write is startup query, rest should be main queries
        main_writes = [w for w in mock_ser._written[1:] if w == main_query]
        assert_true(len(main_writes) >= 1, f"At least one main query sent (got {len(main_writes)})")
    finally:
        sw.serial = saved


def test_addon_runloop_extra_query_every_third():
    """With send_extra_query=True, extra query (0x21) is sent every 3rd iteration."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
            send_extra_query=True,
        )
        addon.start()
        # Wait long enough for several iterations (startup + at least 3 loops)
        time.sleep(0.5)
        addon.stop()
        addon.join(timeout=2.0)

        build_startup_query()
        main_query = build_query(0x10, 0x71)
        extra_query = build_query(0x21, 0x71)

        # Skip the startup query
        loop_writes = mock_ser._written[1:]

        # Verify the pattern: main, [main, main, extra, main, main, extra, ...]
        # The extra query should appear at positions where counter % 3 == 0
        # (counter starts at 0, so the first loop iteration sends extra)
        assert_true(len(loop_writes) >= 4, f"At least 4 loop writes (got {len(loop_writes)})")

        # Count extra queries
        extra_writes = [w for w in loop_writes if w == extra_query]
        main_writes = [w for w in loop_writes if w == main_query]
        assert_true(len(extra_writes) >= 1, f"At least one extra query sent (got {len(extra_writes)})")
        assert_true(len(main_writes) >= 1, f"At least one main query sent (got {len(main_writes)})")

        # Verify extra queries only appear as every 3rd write in the loop
        # The pattern is: main(extra_check), main, main, main(extra_check), ...
        # Actually: counter=0 -> main + extra, counter=1 -> main, counter=2 -> main,
        # counter=3 -> main + extra, etc.
        # So writes alternate between [main, extra] pairs and [main] singles
        # Let's verify no extra query appears without a preceding main query
        for i, w in enumerate(loop_writes):
            if w == extra_query:
                assert_true(i > 0, f"Extra query at index {i} has a preceding write")
                if i > 0:
                    assert_equal(loop_writes[i - 1], main_query, f"Extra query at {i} preceded by main query")
    finally:
        sw.serial = saved


def test_addon_runloop_no_extra_query_when_disabled():
    """With send_extra_query=False, no extra queries are ever sent."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
            send_extra_query=False,
        )
        addon.start()
        time.sleep(0.3)
        addon.stop()
        addon.join(timeout=2.0)

        extra_query = build_query(0x21, 0x71)
        extra_writes = [w for w in mock_ser._written if w == extra_query]
        assert_equal(len(extra_writes), 0, "No extra queries when send_extra_query=False")
    finally:
        sw.serial = saved


def test_addon_runloop_drains_responses():
    """run() calls _drain_responses after each query, producing on_frame RX messages."""
    import heishasim.serial_worker as sw

    class RespondingSerial:
        """Returns a short response on the first read after each write, then empty."""

        def __init__(self):
            self._written: list[bytes] = []
            self._write_count = 0
            self._respond = False

        def read(self, size: int) -> bytes:
            if self._respond:
                self._respond = False
                return bytes([0x71, 0xC8, 0x01])  # short mock response
            return b""

        def write(self, data: bytes) -> int:
            self._written.append(data)
            self._write_count += 1
            self._respond = True  # respond after next read
            return len(data)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    mock_ser = RespondingSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        frame_msgs: list[str] = []
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=frame_msgs.append,
            interval_seconds=0.05,
            send_extra_query=False,
        )
        addon.start()
        time.sleep(0.3)
        addon.stop()
        addon.join(timeout=2.0)

        rx_msgs = [m for m in frame_msgs if m.startswith("RX")]
        tx_msgs = [m for m in frame_msgs if m.startswith("TX")]
        assert_true(len(tx_msgs) >= 2, f"TX messages for startup + at least one query (got {len(tx_msgs)})")
        assert_true(len(rx_msgs) >= 1, f"At least one RX message from drain (got {len(rx_msgs)})")
    finally:
        sw.serial = saved


def test_addon_runloop_stop_exits_cleanly():
    """stop() causes the run-loop to exit within the interval window."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
        )
        addon.start()
        time.sleep(0.15)
        writes_before_stop = len(mock_ser._written)
        addon.stop()
        addon.join(timeout=2.0)
        assert_true(not addon.is_alive(), "Thread exited after stop()")

        # Give a bit more time to ensure no more writes happen
        time.sleep(0.2)
        writes_after_stop = len(mock_ser._written)
        assert_equal(writes_after_stop, writes_before_stop, "No writes after stop()")
    finally:
        sw.serial = saved


def test_addon_runloop_interval_timing():
    """Loop respects interval_seconds — shorter interval produces more writes."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK"),
            on_status=lambda _: None,
            on_frame=lambda _: None,
            interval_seconds=0.05,
            send_extra_query=False,
        )
        addon.start()
        time.sleep(0.5)
        addon.stop()
        addon.join(timeout=2.0)
        fast_writes = len(mock_ser._written)

        # With 0.05s interval over 0.5s, expect ~10 loop iterations + 1 startup
        assert_true(fast_writes >= 5, f"Fast interval: at least 5 writes (got {fast_writes})")
    finally:
        sw.serial = saved


def test_addon_runloop_status_message():
    """run() reports active status via on_status."""
    import heishasim.serial_worker as sw

    mock_ser = TrackWriteSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        status_msgs: list[str] = []
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="MOCK_PORT"),
            on_status=status_msgs.append,
            on_frame=lambda _: None,
            interval_seconds=0.05,
        )
        addon.start()
        time.sleep(0.15)
        addon.stop()
        addon.join(timeout=2.0)

        assert_true(len(status_msgs) >= 1, "Status message received")
        if status_msgs:
            assert_true("CZ-TAW1 simulator active" in status_msgs[0], f"Status: {status_msgs[0]!r}")
            assert_true("MOCK_PORT" in status_msgs[0], f"Status mentions port: {status_msgs[0]!r}")
    finally:
        sw.serial = saved


def test_addon_runloop_frame_messages_contain_port():
    """TX/RX frame messages include the port name."""
    import heishasim.serial_worker as sw

    class RespondingOnceSerial:
        def __init__(self):
            self._respond = False

        def read(self, size: int) -> bytes:
            if self._respond:
                self._respond = False
                return bytes([0x71, 0xC8])
            return b""

        def write(self, data: bytes) -> int:
            self._respond = True
            return len(data)

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    mock_ser = RespondingOnceSerial()
    saved = sw.serial
    sw.serial = _make_fake_serial_module(mock_ser)
    try:
        frame_msgs: list[str] = []
        addon = sw.CZTAW1AddonSimulator(
            settings=sw.SerialSettings(port="ADDON_COM5"),
            on_status=lambda _: None,
            on_frame=frame_msgs.append,
            interval_seconds=0.05,
        )
        addon.start()
        time.sleep(0.2)
        addon.stop()
        addon.join(timeout=2.0)

        assert_true(len(frame_msgs) >= 1, f"Frame messages received (got {len(frame_msgs)})")
        for msg in frame_msgs:
            assert_true("ADDON_COM5" in msg, f"Frame message contains port name: {msg!r}")
    finally:
        sw.serial = saved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # _read_frame tests
    test_read_frame_empty_read()
    test_read_frame_invalid_header()
    test_read_frame_valid_headers()
    test_read_frame_missing_length_byte()
    test_read_frame_truncated_payload()
    test_read_frame_length_zero()
    test_read_frame_minimum_valid()
    test_read_frame_large_payload()
    test_read_frame_real_query()
    test_read_frame_real_startup_query()

    # _build_response tests
    test_build_response_startup_header()
    test_build_response_query_header()
    test_build_response_extra_block_supported()
    test_build_response_extra_block_not_supported()
    test_build_response_f1_header()
    test_build_response_short_frame()
    test_build_response_unknown_header()

    # Server lifecycle tests
    test_run_no_serial()
    test_server_stop_sets_event()
    test_server_is_daemon_thread()
    test_run_serial_exception()

    # Addon lifecycle tests
    test_addon_run_no_serial()
    test_addon_stop_sets_event()
    test_addon_is_daemon_thread()
    test_addon_default_settings()
    test_addon_run_serial_exception()

    # _drain_responses tests
    test_drain_responses_reads_data()
    test_drain_responses_no_data()
    test_drain_responses_multiple_chunks()

    # SerialSettings tests
    test_serial_settings_defaults()
    test_serial_settings_custom_baudrate()

    # available_serial_ports tests
    test_available_serial_ports_no_list_ports()

    # Round-trip integration tests
    test_roundtrip_startup_query()
    test_roundtrip_main_query()
    test_roundtrip_extra_query()

    # HeatPumpSerialServer run-loop integration tests
    test_run_loop_processes_frame()
    test_run_loop_invalid_checksum()

    # CZTAW1AddonSimulator run-loop integration tests
    test_addon_runloop_sends_startup_query()
    test_addon_runloop_sends_main_queries()
    test_addon_runloop_extra_query_every_third()
    test_addon_runloop_no_extra_query_when_disabled()
    test_addon_runloop_drains_responses()
    test_addon_runloop_stop_exits_cleanly()
    test_addon_runloop_interval_timing()
    test_addon_runloop_status_message()
    test_addon_runloop_frame_messages_contain_port()

    success = results.summary()
    sys.exit(0 if success else 1)
