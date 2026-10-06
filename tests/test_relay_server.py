import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from relay_server import Room, create_server

TOKEN_A, TOKEN_B, TOKEN_C = "a" * 20, "b" * 20, "c" * 20


class Recorder:
    def __init__(self):
        self.frames: dict[str, list[dict]] = {}

    def __call__(self, conn_id, text):
        self.frames.setdefault(conn_id, []).append(json.loads(text))

    def of(self, conn_id, msg_type=None):
        msgs = self.frames.get(conn_id, [])
        return [m for m in msgs if msg_type is None or m["type"] == msg_type]

    def clear(self):
        self.frames.clear()


@pytest.fixture
def room():
    rec = Recorder()
    r = Room(rec)
    r.rec = rec
    return r


def test_first_host_and_viewer_welcome(room):
    assert room.join("h", "host", TOKEN_A) is None
    assert room.join("v", "viewer", TOKEN_B) is None
    assert room.rec.of("h", "welcome")[0]["role"] == "host"
    assert room.rec.of("v", "welcome")[0] == {
        "type": "welcome", "peerId": "v", "role": "viewer", "hostId": "h", "peers": ["h", "v"]}
    assert room.rec.of("h", "peer_joined") == [{"type": "peer_joined", "peerId": "v", "joinIndex": 1}]


@pytest.mark.parametrize("role, token, error", [
    ("viewer", TOKEN_A, "room_not_found"),
    ("host", "short", "invalid_token"),
    ("host", "bad token with spaces!!", "invalid_token"),
])
def test_rejections_register_nothing(room, role, token, error):
    assert room.join("x", role, token) == error
    assert room.peers == [] and room.rec.frames == {}
    room.leave("x")  # rejected connection closing is a no-op
    assert room.rec.frames == {}


def test_sync_only_from_host_and_rebuilt(room):
    room.join("h", "host", TOKEN_A)
    room.join("v", "viewer", TOKEN_B)
    room.rec.clear()
    room.on_message("v", json.dumps({"type": "sync", "state": "paused", "videoTime": 0, "wallClock": 1}))
    room.on_message("h", json.dumps({"type": "sync", "state": "playing", "videoTime": 5, "wallClock": 1,
                                     "filename": "m.mp4", "type2": "x", "senderId": "spoof"}))
    assert room.rec.of("h") == []
    assert room.rec.of("v") == [{"type": "sync", "state": "playing", "videoTime": 5, "wallClock": 1,
                                 "filename": "m.mp4", "senderId": "h"}]


@pytest.mark.parametrize("raw", [
    "not json", "1", "null", "[]", "\"x\"", "[" * 3000, "x" * 5000,
    json.dumps({"type": "sync", "state": "playing", "videoTime": 1}),
    json.dumps({"type": "sync", "state": "bad", "videoTime": 1, "wallClock": 1}),
    json.dumps({"type": "sync", "state": "playing", "videoTime": -1, "wallClock": 1}),
    '{"type": "sync", "state": "playing", "videoTime": NaN, "wallClock": 1}',
    json.dumps({"type": "sync", "state": "playing", "videoTime": True, "wallClock": 1}),
    json.dumps({"type": "sync", "state": "playing", "videoTime": 1, "wallClock": 1, "filename": 5}),
    json.dumps({"type": "sync", "state": "playing", "videoTime": 1, "wallClock": 1, "filename": "f" * 300}),
    json.dumps({"type": "welcome", "peerId": "spoof", "role": "host"}),
    json.dumps({"type": "host_changed", "newHostId": "v"}),
    json.dumps({"type": "ping", "clientTime": "x"}),
])
def test_junk_is_dropped_without_raising(room, raw):
    room.join("h", "host", TOKEN_A)
    room.join("v", "viewer", TOKEN_B)
    room.rec.clear()
    room.on_message("h", raw)
    room.on_message("v", raw)
    assert room.rec.frames == {}


def test_ping_pong_only_to_sender(room):
    room.join("h", "host", TOKEN_A)
    room.join("v", "viewer", TOKEN_B)
    room.rec.clear()
    room.on_message("v", json.dumps({"type": "ping", "clientTime": 12.5}))
    assert list(room.rec.frames) == ["v"]
    assert room.rec.of("v", "pong")[0]["clientTime"] == 12.5


def test_transfer_rules(room):
    room.join("h", "host", TOKEN_A)
    room.join("v", "viewer", TOKEN_B)
    room.rec.clear()
    room.on_message("v", json.dumps({"type": "transfer_host", "targetId": "v"}))  # not host
    room.on_message("h", json.dumps({"type": "transfer_host", "targetId": "ghost"}))  # unknown target
    room.on_message("h", json.dumps({"type": "transfer_host", "targetId": "h"}))  # self
    assert room.rec.frames == {} and room.host_id == "h"

    room.on_message("h", json.dumps({"type": "transfer_host", "targetId": "v"}))
    assert room.host_id == "v" and room.owner_token == TOKEN_B
    assert room.rec.of("h", "host_changed") == room.rec.of("v", "host_changed") == [
        {"type": "host_changed", "newHostId": "v"}]


def test_host_drop_promotes_and_owner_reclaims(room):
    room.join("h", "host", TOKEN_A)
    room.join("v1", "viewer", TOKEN_B)
    room.join("v2", "viewer", TOKEN_C)
    room.leave("h")
    assert room.host_id == "v1"
    assert {"type": "host_changed", "newHostId": "v1"} in room.rec.of("v2")

    room.rec.clear()
    room.join("x", "host", "z" * 20)  # wrong token: joins as viewer
    assert room.rec.of("x", "welcome")[0]["role"] == "viewer" and room.host_id == "v1"

    room.join("h2", "host", TOKEN_A)  # owner back with its token
    assert room.host_id == "h2"
    assert {"type": "host_changed", "newHostId": "h2"} in room.rec.of("v1")


def test_tokens_never_sent_and_empty_room_resets(room):
    room.join("h", "host", TOKEN_A)
    room.join("v", "viewer", TOKEN_B)
    room.on_message("h", json.dumps({"type": "transfer_host", "targetId": "v"}))
    sent = json.dumps(room.rec.frames)
    assert TOKEN_A not in sent and TOKEN_B not in sent
    room.leave("h")
    room.leave("v")
    assert (room.peers, room.host_id, room.owner_token, room.tokens) == ([], None, None, {})


# --- over real sockets --------------------------------------------------------

def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


async def _with_server(body):
    async with create_server("127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        await body(f"ws://127.0.0.1:{port}")


async def _recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 2))


def test_socket_flow():
    async def body(base):
        url = base + "/parties/main/ABCD-1234?role={}&token={}"
        async with connect(url.format("viewer", TOKEN_B)) as early:
            assert await _recv(early) == {"type": "error", "code": "room_not_found"}
            with pytest.raises(ConnectionClosed) as closed:
                await early.recv()
            assert closed.value.rcvd.code == 4004

        async with connect(url.format("host", TOKEN_A)) as host, connect(url.format("viewer", TOKEN_B)) as viewer:
            host_welcome = await _recv(host)
            assert (await _recv(viewer))["hostId"] == host_welcome["peerId"]
            await host.send(json.dumps({"type": "sync", "state": "playing", "videoTime": 3,
                                        "wallClock": 1, "filename": "m.mp4"}))
            assert (await _recv(viewer))["type"] == "sync"

        async with connect(base + "/parties/main/abc?role=host&token=" + TOKEN_A) as bad:
            assert await _recv(bad) == {"type": "error", "code": "invalid_room"}

    run(_with_server(body))


def test_bad_paths_and_health():
    async def body(base):
        with pytest.raises(InvalidStatus) as err:
            async with connect(base + "/nope"):
                pass
        assert err.value.response.status_code == 404

        reader, writer = await asyncio.open_connection("127.0.0.1", int(base.rsplit(":", 1)[1]))
        writer.write(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert b"200" in (await reader.readline())
        writer.close()

    run(_with_server(body))
