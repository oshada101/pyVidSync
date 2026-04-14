import sys
import asyncio
import json
import time
import threading
import random
import string
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QWidget,
)
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QFont
from video_player import VideoPlayerWindow
from partysocket_client import PartyKitClient

_DARK_STYLE = """
QDialog {
    background-color: #0d0d0d;
    color: #ffffff;
    font-family: system-ui, sans-serif;
    font-size: 13px;
}
QLabel {
    color: #ffffff;
    background-color: transparent;
}
QPushButton {
    background-color: #2a2a2a;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}
QPushButton:hover {
    background-color: #3a3a3a;
}
QPushButton#accent {
    background-color: #7c3aed;
    font-weight: 600;
}
QPushButton#accent:hover {
    background-color: #6d28d9;
}
QPushButton#copyBtn {
    background-color: #1a1a1a;
    color: #aaaaaa;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
}
QPushButton#copyBtn:hover {
    background-color: #2a2a2a;
    color: #ffffff;
    border-color: #7c3aed;
}
QLineEdit {
    background-color: #1a1a1a;
    color: #ffffff;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
}
QLineEdit:focus {
    border-color: #7c3aed;
}
"""


def _generate_room_code():
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    digits = "".join(random.choices(string.digits, k=3))
    return f"{letters}-{digits}"


class RoleSelectDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.role = None
        self.room_code = None
        self._generated_code = _generate_room_code()

        self.setWindowTitle("Video Sync")
        self.setStyleSheet(_DARK_STYLE)
        self.setMinimumWidth(400)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(32, 32, 32, 32)
        self._root.setSpacing(24)

        title = QLabel("Video Sync")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        self._root.addWidget(title)

        self._choice_widget = self._build_choice()
        self._host_widget = self._build_host_panel()
        self._viewer_widget = self._build_viewer_panel()

        self._root.addWidget(self._choice_widget)
        self._root.addWidget(self._host_widget)
        self._root.addWidget(self._viewer_widget)

        self._host_widget.hide()
        self._viewer_widget.hide()

    def _build_choice(self):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        host_btn = QPushButton("Host")
        host_btn.setObjectName("accent")
        host_btn.setMinimumHeight(56)
        host_btn.setFont(QFont("", 15, QFont.Weight.Bold))
        host_btn.clicked.connect(self._show_host)

        viewer_btn = QPushButton("Viewer")
        viewer_btn.setMinimumHeight(56)
        viewer_btn.setFont(QFont("", 15, QFont.Weight.Bold))
        viewer_btn.clicked.connect(self._show_viewer)

        layout.addWidget(host_btn)
        layout.addWidget(viewer_btn)
        return w

    def _build_host_panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        code_row = QWidget()
        code_row_layout = QHBoxLayout(code_row)
        code_row_layout.setContentsMargins(0, 0, 0, 0)
        code_row_layout.setSpacing(10)

        code_label = QLabel(self._generated_code)
        code_font = QFont("Monospace")
        code_font.setPointSize(28)
        code_font.setBold(True)
        code_label.setFont(code_font)
        code_label.setStyleSheet("color: #7c3aed; letter-spacing: 4px;")
        self._host_code_label = code_label

        copy_btn = QPushButton("⎘")
        copy_btn.setObjectName("copyBtn")
        copy_btn.setFixedSize(30, 30)
        copy_btn.setToolTip("Copy room code")
        copy_btn.clicked.connect(self._copy_code)

        code_row_layout.addStretch()
        code_row_layout.addWidget(code_label)
        code_row_layout.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        code_row_layout.addStretch()

        instruction = QLabel("Share this code with viewers")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet("color: #888888; font-size: 13px;")

        continue_btn = QPushButton("Continue")
        continue_btn.setObjectName("accent")
        continue_btn.setMinimumHeight(44)
        continue_btn.clicked.connect(self._accept_host)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self._show_choice)

        layout.addWidget(code_row)
        layout.addWidget(instruction)
        layout.addWidget(continue_btn)
        layout.addWidget(back_btn)
        return w

    def _build_viewer_panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("Enter room code")
        self._code_input.setMinimumHeight(44)
        self._code_input.returnPressed.connect(self._accept_viewer)

        self._viewer_error = QLabel("")
        self._viewer_error.setStyleSheet("color: #ef4444; font-size: 12px;")
        self._viewer_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._viewer_error.hide()

        join_btn = QPushButton("Join")
        join_btn.setObjectName("accent")
        join_btn.setMinimumHeight(44)
        join_btn.clicked.connect(self._accept_viewer)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(self._show_choice)

        layout.addWidget(self._code_input)
        layout.addWidget(self._viewer_error)
        layout.addWidget(join_btn)
        layout.addWidget(back_btn)
        return w

    def _show_choice(self):
        self._choice_widget.show()
        self._host_widget.hide()
        self._viewer_widget.hide()
        self.adjustSize()

    def _show_host(self):
        self._choice_widget.hide()
        self._host_widget.show()
        self._viewer_widget.hide()
        self.adjustSize()

    def _show_viewer(self):
        self._choice_widget.hide()
        self._host_widget.hide()
        self._viewer_widget.show()
        self._code_input.setFocus()
        self.adjustSize()

    def _copy_code(self):
        QApplication.clipboard().setText(self._generated_code)

    def _accept_host(self):
        self.role = "host"
        self.room_code = self._generated_code
        self.accept()

    def _accept_viewer(self):
        code = self._code_input.text().strip().upper()
        if not code:
            self._viewer_error.setText("Room code required")
            self._viewer_error.show()
            return
        self.role = "viewer"
        self.room_code = code
        self.accept()

    def closeEvent(self, event):
        sys.exit(0)


class _SyncBridge(QObject):
    sync_ready = pyqtSignal(object)


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

    def start(self, app: QApplication):
        self._app = app

        self.video_player = VideoPlayerWindow()
        self.video_player.set_room_code(self._room_code)
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
    app = QApplication(sys.argv)

    dialog = RoleSelectDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    sync_app = SyncApp(dialog.role, dialog.room_code)
    sync_app.start(app)

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
