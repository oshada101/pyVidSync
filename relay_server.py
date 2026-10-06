"""Self-hosted relay server for Video Sync: same protocol as party/server.ts.

Single file, one dependency (websockets), so it can be copied to a small VPS as-is:

    pip install websockets && HOST=0.0.0.0 PORT=1999 python3 relay_server.py

Clients connect to ws://<host>:<port>/parties/main/<ROOM>?role=host|viewer&token=<secret>.
"""
import asyncio
import hmac
import json
import logging
import math
import os
import re
import signal
import time
import uuid
from http import HTTPStatus
from urllib.parse import parse_qs, unquote, urlsplit

from websockets.asyncio.server import ServerConnection, broadcast, serve

log = logging.getLogger("relay")

PATH_RE = re.compile(r"^/parties/main/([^/]+)$")
ROOM_RE = re.compile(r"^[A-Z]{4}-\d{4}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_FRAME_BYTES = 16 * 1024
MAX_MESSAGE_LEN = 4096
MAX_FILENAME_LEN = 255
CLOSE_CODES = {"invalid_room": 4000, "invalid_token": 4001, "room_not_found": 4004}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Room:
    """Room state and protocol rules, independent of sockets. `send(conn_id, text)` delivers one frame."""

    def __init__(self, send):
        self._send = send
        self.peers: list[str] = []  # join order
        self.host_id: str | None = None
        self.owner_token: str | None = None
        self.tokens: dict[str, str] = {}  # secrets: never sent to any client

    def send(self, conn_id: str, msg: dict):
        self._send(conn_id, json.dumps(msg))

    def broadcast(self, msg: dict, without: tuple[str, ...] = ()):
        data = json.dumps(msg)
        for peer in self.peers:
            if peer not in without:
                self._send(peer, data)

    def join(self, conn_id: str, role: str, token: str) -> str | None:
        """Register a connection; returns an error code if it must be rejected."""
        if not TOKEN_RE.fullmatch(token):
            return "invalid_token"
        is_host = False
        if role == "host":
            if self.owner_token is None:
                self.owner_token = token
            is_host = hmac.compare_digest(token, self.owner_token)
        elif not self.peers:
            return "room_not_found"

        self.peers.append(conn_id)
        self.tokens[conn_id] = token
        if is_host and self.host_id != conn_id:
            previous, self.host_id = self.host_id, conn_id
            if previous is not None:  # owner reclaiming after a reconnect
                self.broadcast({"type": "host_changed", "newHostId": conn_id}, without=(conn_id,))

        self.send(conn_id, {
            "type": "welcome",
            "peerId": conn_id,
            "role": "host" if self.host_id == conn_id else "viewer",
            "hostId": self.host_id,
            "peers": list(self.peers),
        })
        self.broadcast({"type": "peer_joined", "peerId": conn_id, "joinIndex": len(self.peers) - 1},
                       without=(conn_id,))
        return None

    def on_message(self, conn_id: str, raw: str):
        if len(raw) > MAX_MESSAGE_LEN:
            return
        try:
            msg = json.loads(raw)
        except (ValueError, RecursionError):
            return
        if not isinstance(msg, dict):
            return

        msg_type = msg.get("type")
        if msg_type == "ping":
            if _is_number(msg.get("clientTime")):
                self.send(conn_id, {"type": "pong", "clientTime": msg["clientTime"], "serverTime": time.time()})
        elif msg_type in ("sync", "heartbeat"):
            if conn_id != self.host_id:
                return
            state, video_time, wall_clock = msg.get("state"), msg.get("videoTime"), msg.get("wallClock")
            filename = msg.get("filename", "")
            if (state not in ("playing", "paused") or not _is_number(video_time) or video_time < 0
                    or not _is_number(wall_clock)
                    or not isinstance(filename, str) or len(filename) > MAX_FILENAME_LEN):
                return
            # Rebuild from validated fields only; never relay the raw object.
            self.broadcast({"type": msg_type, "state": state, "videoTime": video_time,
                            "wallClock": wall_clock, "filename": filename, "senderId": conn_id},
                           without=(conn_id,))
        elif msg_type == "transfer_host":
            target = msg.get("targetId")
            if conn_id != self.host_id or not isinstance(target, str) or target == conn_id \
                    or target not in self.peers:
                return
            self.host_id = target
            self.owner_token = self.tokens.get(target)
            self.broadcast({"type": "host_changed", "newHostId": target})

    def leave(self, conn_id: str):
        if conn_id not in self.peers:
            return
        self.peers.remove(conn_id)
        self.tokens.pop(conn_id, None)
        if self.host_id == conn_id:
            # owner_token is kept so the owner can reclaim host after reconnecting.
            self.host_id = self.peers[0] if self.peers else None
            if self.host_id is not None:
                self.broadcast({"type": "host_changed", "newHostId": self.host_id})
        self.broadcast({"type": "peer_left", "peerId": conn_id})
        if not self.peers:
            self.host_id = None
            self.owner_token = None
            self.tokens.clear()


def create_server(host: str, port: int):
    """Returns the websockets server (an async context manager)."""
    rooms: dict[str, Room] = {}
    sockets: dict[str, ServerConnection] = {}

    def deliver(conn_id: str, text: str):
        ws = sockets.get(conn_id)
        if ws is not None:
            broadcast([ws], text)  # non-blocking send; skips closed sockets

    def process_request(connection, request):
        path = urlsplit(request.path).path
        if PATH_RE.fullmatch(path) and request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        if path == "/":
            return connection.respond(HTTPStatus.OK, "videosync ok\n")
        return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")

    async def handler(ws: ServerConnection):
        parts = urlsplit(ws.request.path)
        room_id = unquote(PATH_RE.fullmatch(parts.path).group(1))
        query = parse_qs(parts.query)
        role = query.get("role", [""])[0]
        token = query.get("token", [""])[0]

        if not ROOM_RE.fullmatch(room_id):
            error, room = "invalid_room", None
        else:
            room = rooms.setdefault(room_id, Room(deliver))
            conn_id = str(uuid.uuid4())
            sockets[conn_id] = ws
            error = room.join(conn_id, role, token)
        if error:
            if room is not None:
                sockets.pop(conn_id, None)
                if not room.peers:
                    rooms.pop(room_id, None)
            await ws.send(json.dumps({"type": "error", "code": error}))
            await ws.close(CLOSE_CODES[error], error)
            return

        try:
            async for raw in ws:
                if isinstance(raw, str):
                    try:
                        room.on_message(conn_id, raw)
                    except Exception:
                        log.exception("Message handling failed")
        finally:
            sockets.pop(conn_id, None)
            room.leave(conn_id)
            if not room.peers and rooms.get(room_id) is room:
                del rooms[room_id]

    return serve(handler, host, port, process_request=process_request, max_size=MAX_FRAME_BYTES)


async def _serve_forever(host: str, port: int):
    async with create_server(host, port):
        log.info("Listening on ws://%s:%d/parties/main/<ROOM>", host, port)
        stop = asyncio.get_running_loop().create_future()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.cancel)
        try:
            await stop
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="[%(name)s] %(message)s")
    asyncio.run(_serve_forever(os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "1999"))))
