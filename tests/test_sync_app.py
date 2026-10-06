import time

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtTest import QTest

from sync_logic import ClockSync


class FakePlayer(QObject):
    playRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    seekRequested = pyqtSignal(float)
    fileLoaded = pyqtSignal()
    transferRequested = pyqtSignal(str)
    closing = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.mode = None
        self.loaded_file = "/videos/movie.mp4"
        self.playing = False
        self.position = 0.0
        self.calls = []
        self.warning = None
        self.transfer_targets = []

    def set_room_code(self, code): pass
    def set_connection_status(self, text, ok): pass
    def show(self): pass
    def set_host_mode(self): self.mode = "host"
    def set_viewer_mode(self): self.mode = "viewer"
    def set_transfer_targets(self, targets): self.transfer_targets = targets
    def update_host_status(self, *args): pass
    def show_warning(self, text): self.warning = text
    def clear_warning(self): self.warning = None
    def is_playing(self): return self.playing
    def get_current_time(self): return self.position
    def get_duration(self): return 0.0

    def play(self):
        self.playing = True
        self.calls.append(("play",))
        self.playRequested.emit()

    def pause(self):
        self.playing = False
        self.calls.append(("pause",))
        self.pauseRequested.emit()

    def seek_to(self, t):
        self.position = t
        self.calls.append(("seek", t))
        self.seekRequested.emit(t)


class FakeClient:
    def __init__(self):
        self.clock = ClockSync()
        self.sent = []
        self.on_message = None
        self.on_status = None
        self.stopped = 0

    def start(self): pass
    def stop(self): self.stopped += 1

    def send_threadsafe(self, msg):
        self.sent.append(msg)
        return True


@pytest.fixture
def make_app(qapp):
    from main import SyncApp

    def make(role_hint="viewer"):
        player, client = FakePlayer(), FakeClient()
        app = SyncApp(role_hint, "ABCD-1234", player, client)
        app.start()
        client.sent.clear()
        return app, player, client
    return make


def welcome(role, peer_id="me", host_id="h1", peers=("h1", "me")):
    return {"type": "welcome", "peerId": peer_id, "role": role, "hostId": host_id, "peers": list(peers)}


def sync_msg(msg_type="sync", state="playing", video_time=10.0, wall_clock=None, sender="h1"):
    return {"type": msg_type, "state": state, "videoTime": video_time,
            "wallClock": time.time() if wall_clock is None else wall_clock,
            "filename": "movie.mp4", "senderId": sender}


def test_welcome_viewer(make_app):
    app, player, _ = make_app("host")  # server overrides the dialog's hint
    app._on_message(welcome("viewer"))
    assert app.role == "viewer" and player.mode == "viewer"
    assert app._silence_timer.isActive() and not app._heartbeat_timer.isActive()


def test_welcome_host_announces_state(make_app):
    app, player, client = make_app("host")
    app._on_message(welcome("host", peer_id="h1", peers=("h1",)))
    assert app.role == "host" and player.mode == "host"
    assert app._heartbeat_timer.isActive()
    assert client.sent[-1]["type"] == "sync"


def test_reconnect_welcome_does_not_duplicate_timers(make_app):
    app, _, _ = make_app()
    for _ in range(3):
        app._on_message(welcome("viewer"))
    assert app.findChildren(type(app._silence_timer)) == [app._heartbeat_timer, app._silence_timer, app._sync_debounce]


def test_sync_applies_with_server_clock(make_app):
    app, player, client = make_app()
    app._on_message(welcome("viewer"))
    client.clock.offset = 100.0  # server clock is 100s ahead of ours
    app._on_message(sync_msg(wall_clock=time.time() + 100.0 - 2.0))
    assert player.calls[0] == ("play",)
    assert player.calls[1][0] == "seek" and player.calls[1][1] == pytest.approx(12.0, abs=0.2)
    assert client.sent == []  # viewer never echoes


def test_sync_from_non_host_ignored(make_app):
    app, player, _ = make_app()
    app._on_message(welcome("viewer"))
    app._on_message(sync_msg(sender="intruder"))
    assert player.calls == []


@pytest.mark.parametrize("bad", [
    {"type": "sync", "senderId": "h1"},
    {"type": "sync", "state": "playing", "videoTime": "x", "wallClock": 1, "senderId": "h1"},
    {"type": "welcome", "peers": "not-a-list"},
    {"type": "host_changed"},
    {"type": "peer_joined", "peerId": ["x"]},
])
def test_malformed_messages_never_raise(make_app, bad):
    app, _, _ = make_app()
    app._on_message(welcome("viewer"))
    app._on_message(bad)  # must not raise: PyQt aborts on exceptions escaping slots


def test_heartbeat_only_corrects_real_drift(make_app):
    app, player, _ = make_app()
    app._on_message(welcome("viewer"))
    player.playing, player.position = True, 10.2
    app._on_message(sync_msg("heartbeat", video_time=10.0))
    assert player.calls == []
    player.position = 15.0
    app._on_message(sync_msg("heartbeat", video_time=10.0))
    assert ("seek", pytest.approx(10.0, abs=0.2)) in player.calls


def test_heartbeat_state_change_applies(make_app):
    app, player, _ = make_app()
    app._on_message(welcome("viewer"))
    player.playing, player.position = True, 10.0
    app._on_message(sync_msg("heartbeat", state="paused", video_time=10.0))
    assert player.calls[-1] == ("pause",)


def test_host_changed_promotes_and_demotes(make_app):
    app, player, _ = make_app()
    app._on_message(welcome("viewer"))
    app._on_message({"type": "host_changed", "newHostId": "me"})
    assert app.role == "host" and player.mode == "host"
    app._on_message({"type": "host_changed", "newHostId": "h1"})  # e.g. original owner reclaimed
    assert app.role == "viewer" and player.mode == "viewer"


def test_transfer_waits_for_server_confirmation(make_app):
    app, player, client = make_app("host")
    app._on_message(welcome("host", peer_id="h1", host_id="h1", peers=("h1",)))
    app._on_message({"type": "peer_joined", "peerId": "v1"})
    assert [p for _, p in player.transfer_targets] == ["v1"]
    client.sent.clear()

    app._transfer_host("unknown")
    assert client.sent == []
    app._transfer_host("v1")
    assert client.sent == [{"type": "transfer_host", "targetId": "v1"}]
    assert app.role == "host"

    app._on_message({"type": "peer_left", "peerId": "v1"})
    assert player.transfer_targets == []


def test_host_local_controls_are_debounced(make_app):
    app, player, client = make_app("host")
    app._on_message(welcome("host", peer_id="h1", host_id="h1", peers=("h1",)))
    client.sent.clear()
    for t in (1.0, 2.0, 3.0, 4.0):
        player.seek_to(t)
    assert client.sent == []
    QTest.qWait(250)
    syncs = [m for m in client.sent if m["type"] == "sync"]
    assert len(syncs) == 1 and syncs[0]["videoTime"] == 4.0


def test_heartbeat_without_file_reports_empty(make_app):
    app, player, client = make_app("host")
    app._on_message(welcome("host", peer_id="h1", host_id="h1", peers=("h1",)))
    player.loaded_file = None
    app._send_heartbeat()
    assert client.sent[-1] == {**client.sent[-1], "type": "heartbeat", "state": "paused",
                               "videoTime": 0.0, "filename": ""}


def test_host_silence_warns_and_pauses(make_app):
    app, player, _ = make_app()
    app._on_message(welcome("viewer"))
    app._last_host_seen -= 10
    app._check_host_silence()
    assert player.warning and player.calls[-1] == ("pause",)
    app._on_message(sync_msg("heartbeat"))
    assert player.warning is None


def test_room_not_found_not_overwritten_by_silence(make_app):
    app, player, _ = make_app()
    app._on_message({"type": "error", "code": "room_not_found"})
    app._last_host_seen -= 10
    app._check_host_silence()
    assert "Room not found" in player.warning


def test_stop_is_idempotent(make_app):
    app, player, client = make_app()
    player.closing.emit()
    app.stop()
    assert client.stopped == 2 and not app._silence_timer.isActive()
