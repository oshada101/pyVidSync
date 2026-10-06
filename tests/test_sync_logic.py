import math

import pytest

from sync_logic import (
    ClockSync, SyncState, build_ws_uri, expected_position, generate_room_code, generate_token,
    needs_correction, normalize_host, normalize_room_code, parse_sync,
)


def test_room_code_format_and_roundtrip():
    code = generate_room_code()
    assert normalize_room_code(code) == code
    assert len({generate_room_code() for _ in range(50)}) > 45


@pytest.mark.parametrize("raw, expected", [
    (" abcd-1234 ", "ABCD-1234"),
    ("ABC-123", None),
    ("ABCD1234", None),
    ("ABCD-1234/../x", None),
    ("", None),
])
def test_normalize_room_code(raw, expected):
    assert normalize_room_code(raw) == expected


def test_token_matches_server_rule():
    import re
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,128}", generate_token())


@pytest.mark.parametrize("raw, expected", [
    ("example.partykit.dev", "example.partykit.dev"),
    ("  localhost:1999/ ", "localhost:1999"),
    ("https://example.partykit.dev", "wss://example.partykit.dev"),
    ("http://192.168.1.5:1999", "ws://192.168.1.5:1999"),
    ("ws://192.168.1.5:1999", "ws://192.168.1.5:1999"),
    ("ftp://example.com", None),
    ("example.com/path", None),
    ("", None),
    ("wss://", None),
])
def test_normalize_host(raw, expected):
    assert normalize_host(raw) == expected


def test_build_ws_uri_schemes_and_quoting():
    assert build_ws_uri("localhost:1999", "ABCD-1234", "host", "t").startswith("ws://localhost:1999/parties/main/ABCD-1234?")
    assert build_ws_uri("127.0.0.1:8080", "R", "viewer", "t").startswith("ws://127.0.0.1:8080/")
    assert build_ws_uri("example.partykit.dev", "R", "viewer", "t").startswith("wss://example.partykit.dev/")
    assert build_ws_uri("ws://10.0.0.2:1999", "R", "viewer", "t").startswith("ws://10.0.0.2:1999/")
    uri = build_ws_uri("example.dev", "a/b?c", "viewer", "tok en")
    assert "/parties/main/a%2Fb%3Fc?" in uri
    assert uri.endswith("role=viewer&token=tok+en")


def test_parse_sync_valid():
    s = parse_sync({"state": "playing", "videoTime": 12, "wallClock": 100.5, "filename": "a.mp4"})
    assert s == SyncState("playing", 12.0, 100.5, "a.mp4")


@pytest.mark.parametrize("msg", [
    {"state": "playing", "videoTime": 1.0},
    {"state": "stopped", "videoTime": 1.0, "wallClock": 1.0},
    {"state": "paused", "videoTime": -1, "wallClock": 1.0},
    {"state": "paused", "videoTime": math.nan, "wallClock": 1.0},
    {"state": "paused", "videoTime": 1.0, "wallClock": math.inf},
    {"state": "paused", "videoTime": True, "wallClock": 1.0},
    {"state": "paused", "videoTime": "1", "wallClock": 1.0},
])
def test_parse_sync_rejects_malformed(msg):
    assert parse_sync(msg) is None


def test_parse_sync_non_string_filename_dropped():
    assert parse_sync({"state": "paused", "videoTime": 0, "wallClock": 0, "filename": 5}).filename == ""


def test_expected_position():
    playing = SyncState("playing", 10.0, 100.0)
    assert expected_position(playing, now=102.5) == pytest.approx(12.5)
    assert expected_position(playing, now=99.0) == pytest.approx(10.0)  # clock jitter never rewinds
    assert expected_position(playing, now=200.0, duration=30.0) == 30.0
    assert expected_position(SyncState("paused", 10.0, 100.0), now=150.0) == 10.0


def test_needs_correction():
    assert not needs_correction(10.0, 10.5)
    assert needs_correction(10.0, 11.0)


def test_clock_sync_prefers_lowest_rtt():
    clock = ClockSync()
    assert clock.now(50.0) == 50.0
    clock.add_sample(client_send=100.0, server_time=105.2, client_recv=100.4)  # rtt 0.4, offset 5.0
    clock.add_sample(client_send=200.0, server_time=207.0, client_recv=202.0)  # rtt 2.0, noisy
    assert clock.offset == pytest.approx(5.0)
    clock.add_sample(client_send=300.0, server_time=290.0, client_recv=299.0)  # negative rtt ignored
    assert clock.offset == pytest.approx(5.0)
