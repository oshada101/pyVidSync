import asyncio
import json

from partysocket_client import PartyKitClient


class FakeWS:
    def __init__(self, frames):
        self._frames = list(frames)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)


def run_receive(frames, handler):
    client = PartyKitClient("ABCD-1234", "viewer", "x" * 32)
    client.ws = FakeWS(frames)
    client.on_message = handler
    asyncio.run(client._receive_messages())
    return client


def test_receive_filters_bad_frames_and_survives_handler_errors():
    seen = []

    def handler(data):
        seen.append(data)
        if data.get("boom"):
            raise RuntimeError("handler bug")

    client = run_receive([
        "not json", "[]", "1", "null", json.dumps({"no": "type"}), json.dumps({"type": 5}),
        json.dumps({"type": "sync", "boom": True}),
        json.dumps({"type": "pong", "clientTime": 0.0, "serverTime": 1.0}),
        json.dumps({"type": "error", "code": "room_not_found"}),
        json.dumps({"type": "peer_left", "peerId": "p"}),
    ], handler)

    assert [d["type"] for d in seen] == ["sync", "error", "peer_left"]  # pong handled internally
    assert client._last_error == "room_not_found"
    assert len(client.clock._samples) == 1


def test_send_threadsafe_without_connection():
    client = PartyKitClient("ABCD-1234", "viewer", "x" * 32)
    assert client.send_threadsafe({"type": "ping"}) is False
    client.stop()  # never started: must not raise
