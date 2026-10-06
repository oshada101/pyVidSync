import asyncio
import itertools
import json
import logging
import sys
import threading
import time

import websockets
from dotenv import load_dotenv

from settings import resolve_host
from sync_logic import ClockSync, build_ws_uri, is_number, normalize_host

if not getattr(sys, 'frozen', False):
    load_dotenv()

log = logging.getLogger("partykit")

MAX_RECONNECT_DELAY_SEC = 30.0
PING_BURST = 4  # quick pings right after connecting so the clock offset converges fast
PING_BURST_INTERVAL_SEC = 0.5
PING_INTERVAL_SEC = 10.0
FATAL_ERRORS = {"invalid_room", "invalid_token"}


class PartyKitClient:
    """WebSocket client running its own asyncio loop on a daemon thread.

    Callbacks fire on that network thread; the GUI must marshal them onto the Qt thread.
    """

    def __init__(self, room_id: str, role: str, token: str):
        self.room_id = room_id
        self.role = role
        self.token = token
        self.clock = ClockSync()
        self.ws = None
        self.on_message = None  # (dict) -> None
        self.on_status = None  # (text: str, ok: bool) -> None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="partykit", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0):
        loop, task = self._loop, self._task
        if loop and task:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:  # loop already closed
                pass
        if self._thread:
            self._thread.join(timeout)

    def send_threadsafe(self, message: dict) -> bool:
        """Queue a message from any thread. Returns False if not connected."""
        loop = self._loop
        if loop is None or self.ws is None:
            return False
        asyncio.run_coroutine_threadsafe(self.send(message), loop)
        return True

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_forever())
        except asyncio.CancelledError:
            pass
        finally:
            self._loop.close()

    def _status(self, text: str, ok: bool):
        if self.on_status:
            self.on_status(text, ok)

    async def _connect_forever(self):
        self._task = asyncio.current_task()
        host = normalize_host(resolve_host() or "")
        if not host:
            log.error("PartyKit host missing or invalid. Set it in Settings or via PARTYKIT_HOST.")
            self._status("Server not configured", False)
            return
        uri = build_ws_uri(host, self.room_id, self.role, self.token)
        log.info("Connecting to %s", uri.split("?", 1)[0])  # query carries the secret token

        delay = 1.0
        while True:
            self._last_error = None
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
                    self.ws = ws
                    delay = 1.0
                    self._status("Joining room…", False)
                    pinger = asyncio.create_task(self._ping_loop())
                    try:
                        await self._receive_messages()
                    finally:
                        pinger.cancel()
            except (OSError, asyncio.TimeoutError, websockets.exceptions.WebSocketException) as e:
                log.warning("Disconnected: %s", e)
            except Exception:
                log.exception("Unexpected connection error")
            finally:
                self.ws = None

            if self._last_error in FATAL_ERRORS:
                self._status(f"Rejected by server ({self._last_error})", False)
                return
            if self._last_error == "room_not_found":
                self._status("Room not found, retrying…", False)
            else:
                self._status(f"Reconnecting in {delay:.0f}s…", False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RECONNECT_DELAY_SEC)

    async def _receive_messages(self):
        async for raw in self.ws:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                log.warning("Ignoring non-JSON message")
                continue
            if not isinstance(data, dict) or not isinstance(data.get("type"), str):
                continue
            if data["type"] == "pong":
                self._on_pong(data)
                continue
            if data["type"] == "welcome":
                log.info("Joined room %s as %s", self.room_id, data.get("role"))
                self._status("Connected", True)
            elif data["type"] == "error":
                self._last_error = data.get("code")
            log.debug("Received: %s", data)
            if self.on_message:
                try:
                    self.on_message(data)
                except Exception:
                    log.exception("Message handler failed")

    async def _ping_loop(self):
        for i in itertools.count():
            await self.send({"type": "ping", "clientTime": time.time()})
            await asyncio.sleep(PING_BURST_INTERVAL_SEC if i < PING_BURST else PING_INTERVAL_SEC)

    def _on_pong(self, data: dict):
        client_time, server_time = data.get("clientTime"), data.get("serverTime")
        if is_number(client_time) and is_number(server_time):
            self.clock.add_sample(client_time, server_time, time.time())

    async def send(self, message: dict):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(message))
        except websockets.exceptions.ConnectionClosed:
            pass
