import sys
import asyncio
import json
import time
import threading
import random
import string
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from video_player import VideoPlayerWindow
from partysocket_client import PartyKitClient


class _SyncBridge(QObject):
    sync_ready = pyqtSignal(object)


def _startup_prompt():
    print("=== Video Sync ===")
    print("[1] Host — create room")
    print("[2] Viewer — join room")
    while True:
        choice = input("Choice: ").strip()
        if choice == "1":
            letters = "".join(random.choices(string.ascii_uppercase, k=3))
            digits = "".join(random.choices(string.digits, k=3))
            room_code = f"{letters}-{digits}"
            print(f"Room code: {room_code}  (share this with viewers)")
            return "host", room_code
        elif choice == "2":
            room_code = input("Enter room code: ").strip().upper()
            return "viewer", room_code
        else:
            print("Enter 1 or 2.")


class SyncApp:
    def __init__(self, role_hint, room_code):
        self.role = None
        self._role_hint = role_hint
        self._room_code = room_code
        self.video_player = None
        self.party_client = None
        self._app = None
        self._loop = None
        self._thread = None
        self._applying_sync = False
        self._bridge = _SyncBridge()
        self.peer_id = None
        self._host_peer_id = None
        self._last_heartbeat_time = time.time()
        self._host_disconnect_warned = False
        self._peers: list[str] = []

    def start(self):
        self._app = QApplication(sys.argv)

        self.video_player = VideoPlayerWindow()
        self.video_player.show()

        self.party_client = PartyKitClient(self._room_code)

        self._bridge.sync_ready.connect(self._do_apply_sync)
        self._setup_peer_callbacks()
        self._setup_video_signals()
        self._start_connection()
        self._start_stdin_thread()

        return self._app

    def _apply_role(self, role):
        self.role = role
        if role == "viewer":
            self.video_player.set_viewer_mode()
            self._last_heartbeat_time = time.time()
            self._host_disconnect_warned = False
            if self._loop:
                self._loop.create_task(self._silence_loop())
        else:
            self.video_player.set_host_mode()
            if self._loop:
                self._loop.create_task(self._heartbeat_loop())

    def _start_connection(self):
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._connect_async())

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    async def _connect_async(self):
        try:
            await self.party_client.connect()
        except Exception as e:
            print(f"[PartyKit] Connection failed: {e}")

    def _setup_video_signals(self):
        self.video_player.playRequested.connect(self._on_play)
        self.video_player.pauseRequested.connect(self._on_pause)
        self.video_player.seekRequested.connect(self._on_seek)
        self.video_player.positionChanged.connect(self._on_position_changed)

    def _setup_peer_callbacks(self):
        def on_message(data):
            msg_type = data.get("type")

            if msg_type == "welcome":
                self.peer_id = data.get("peerId")
                role = data.get("role")
                if role:
                    self._apply_role(role)
            elif msg_type == "heartbeat" and self.role == "viewer":
                self._last_heartbeat_time = time.time()
                if self._host_disconnect_warned:
                    self._host_disconnect_warned = False
                    self.video_player.clear_warning()
            elif msg_type == "peer_joined":
                peer = data.get("peerId")
                if peer and peer != self.peer_id and peer not in self._peers:
                    self._peers.append(peer)
                if self.role == "host":
                    print(f"[Sync] Viewer joined: {peer}  (peers: {self._peers})")
            elif msg_type == "peer_left":
                peer = data.get("peerId")
                if peer in self._peers:
                    self._peers.remove(peer)
            elif msg_type == "host_changed":
                new_host = data.get("newHostId")
                if new_host and new_host == self.peer_id:
                    self._apply_role("host")
                    print("[Sync] Promoted to host")
                else:
                    self._host_peer_id = new_host
            elif msg_type == "sync" and self.role == "viewer":
                self._apply_sync(data)

        self.party_client.set_on_message(on_message)
        self.party_client.set_on_connect(self._on_peer_connect)

    def _on_peer_connect(self):
        print("[PartyKit] Connected!")
        if self._role_hint == "host":
            self._send_sync_state()

    def _on_play(self):
        if self.role == "host" and not self._applying_sync:
            self._send_sync_state()

    def _on_pause(self):
        if self.role == "host" and not self._applying_sync:
            self._send_sync_state()

    def _on_seek(self, position):
        if self.role == "host" and not self._applying_sync:
            self._send_sync_state()

    def _on_position_changed(self, position):
        pass

    async def _heartbeat_loop(self):
        while self.role == "host":
            if self.party_client.ws:
                await self.party_client.broadcast({"type": "heartbeat", "wallClock": time.time()})
            await asyncio.sleep(1.0)

    async def _silence_loop(self):
        while self.role == "viewer":
            if time.time() - self._last_heartbeat_time > 3.0:
                if not self._host_disconnect_warned:
                    self._host_disconnect_warned = True
                    self.video_player.show_warning("Host disconnected — waiting...")
                    self.video_player.pause()
            await asyncio.sleep(1.0)

    def _send_sync_state(self):
        if not hasattr(self.party_client, 'ws') or not self.party_client.ws:
            return

        msg = {
            "type": "sync",
            "state": "playing" if self.video_player.is_playing() else "paused",
            "videoTime": self.video_player.get_current_time(),
            "wallClock": time.time(),
        }

        if self._loop:
            asyncio.run_coroutine_threadsafe(self.party_client.broadcast(msg), self._loop)
        print(f"[Sync] Sent: {msg['state']} at {msg['videoTime']:.1f}s")

    def _start_stdin_thread(self):
        def read_stdin():
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                self._handle_command(line.strip())

        t = threading.Thread(target=read_stdin, daemon=True)
        t.start()

    def _handle_command(self, line: str):
        parts = line.split()
        if not parts:
            return
        if parts[0] == "transfer" and len(parts) == 2:
            if self.role != "host":
                print("[Sync] Not host — cannot transfer")
                return
            target_id = parts[1]
            msg = {"type": "transfer_host", "targetId": target_id}
            if self._loop:
                asyncio.run_coroutine_threadsafe(self.party_client.broadcast(msg), self._loop)
            self.role = "viewer"
            self.video_player.set_viewer_mode()

    def _apply_sync(self, msg):
        self._bridge.sync_ready.emit(msg)

    def _do_apply_sync(self, msg):
        latency = time.time() - msg["wallClock"]
        video_time = msg["videoTime"] + (latency if msg["state"] == "playing" else 0)

        self._applying_sync = True
        self.video_player.seek_to(video_time)
        if msg["state"] == "playing":
            self.video_player.play()
        else:
            self.video_player.pause()
        self._applying_sync = False


def main():
    role_hint, room_code = _startup_prompt()
    sync_app = SyncApp(role_hint, room_code)
    app = sync_app.start()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print("Exiting...")


if __name__ == "__main__":
    main()
