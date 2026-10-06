import logging
import os
import sys
import time

os.environ["LIBPLACEBO_CPU"] = "1"

# PyInstaller's bootloader changes the DLL search path, which breaks python-vlc's libvlc loading
# (see 5273fa2). Reset it before vlc is imported; the rest of the path setup lives in rthook_vlc.py.
if getattr(sys, 'frozen', False) and sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetDllDirectoryW(None)

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QWidget,
)
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtGui import QFont
from video_player import VideoPlayerWindow
from partysocket_client import PartyKitClient
from settings import load_settings, save_settings, resolve_host
from sync_logic import (
    SyncState, expected_position, generate_room_code, generate_token,
    needs_correction, normalize_host, normalize_room_code, parse_sync,
)

log = logging.getLogger("sync")

HEARTBEAT_INTERVAL_MS = 1000
SILENCE_CHECK_INTERVAL_MS = 1000
HOST_SILENCE_TIMEOUT_SEC = 3.0
SYNC_DEBOUNCE_MS = 120  # coalesces slider drags and key-repeat seeks into one broadcast
FILE_LOAD_SETTLE_MS = 300  # VLC ignores seeks until playback has actually started

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



class RoleSelectDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.role = None
        self.room_code = None
        self._generated_code = generate_room_code()

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
        self._settings_widget = self._build_settings_panel()
        self._panels = (self._choice_widget, self._host_widget, self._viewer_widget, self._settings_widget)
        for panel in self._panels:
            self._root.addWidget(panel)
        self._show_panel(self._choice_widget)

    @staticmethod
    def _error_label():
        label = QLabel("")
        label.setStyleSheet("color: #ef4444; font-size: 12px;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.hide()
        return label

    def _build_choice(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setSpacing(12)
        outer.setContentsMargins(0, 0, 0, 0)

        btn_row = QWidget()
        layout = QHBoxLayout(btn_row)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        host_btn = QPushButton("Host")
        host_btn.setObjectName("accent")
        host_btn.setMinimumHeight(56)
        host_btn.setFont(QFont("", 15, QFont.Weight.Bold))
        host_btn.clicked.connect(lambda: self._show_panel(self._host_widget))

        viewer_btn = QPushButton("Viewer")
        viewer_btn.setMinimumHeight(56)
        viewer_btn.setFont(QFont("", 15, QFont.Weight.Bold))
        viewer_btn.clicked.connect(lambda: self._show_panel(self._viewer_widget))

        layout.addWidget(host_btn)
        layout.addWidget(viewer_btn)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.setStyleSheet(
            "background: transparent; color: #555555; font-size: 12px; border: none; padding: 0;"
        )
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(lambda: self._show_panel(self._settings_widget))

        outer.addWidget(btn_row)
        outer.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignRight)
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

        self._copy_btn = QPushButton("⎘")
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setFixedSize(30, 30)
        self._copy_btn.setToolTip("Copy room code")
        self._copy_btn.clicked.connect(self._copy_code)

        code_row_layout.addStretch()
        code_row_layout.addWidget(code_label)
        code_row_layout.addWidget(self._copy_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        code_row_layout.addStretch()

        instruction = QLabel("Share this code with viewers")
        instruction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction.setStyleSheet("color: #888888; font-size: 13px;")

        self._host_error = self._error_label()

        continue_btn = QPushButton("Continue")
        continue_btn.setObjectName("accent")
        continue_btn.setMinimumHeight(44)
        continue_btn.clicked.connect(self._accept_host)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(lambda: self._show_panel(self._choice_widget))

        layout.addWidget(code_row)
        layout.addWidget(instruction)
        layout.addWidget(self._host_error)
        layout.addWidget(continue_btn)
        layout.addWidget(back_btn)
        return w

    def _build_viewer_panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("Enter room code (e.g. ABCD-1234)")
        self._code_input.setMinimumHeight(44)
        self._code_input.returnPressed.connect(self._accept_viewer)

        self._viewer_error = self._error_label()

        join_btn = QPushButton("Join")
        join_btn.setObjectName("accent")
        join_btn.setMinimumHeight(44)
        join_btn.clicked.connect(self._accept_viewer)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(lambda: self._show_panel(self._choice_widget))

        layout.addWidget(self._code_input)
        layout.addWidget(self._viewer_error)
        layout.addWidget(join_btn)
        layout.addWidget(back_btn)
        return w

    def _build_settings_panel(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("PartyKit Host")
        label.setStyleSheet("color: #888888; font-size: 12px;")

        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("e.g. myserver.partykit.dev or ws://192.168.1.5:1999")
        self._host_input.setText(load_settings().get("partykit_host", ""))
        self._host_input.setMinimumHeight(44)

        env_note = QLabel("PARTYKIT_HOST environment variable is set and overrides this value")
        env_note.setStyleSheet("color: #f59e0b; font-size: 11px;")
        env_note.setWordWrap(True)
        env_note.setVisible(bool(os.environ.get("PARTYKIT_HOST", "").strip()))

        self._settings_status = QLabel("")
        self._settings_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._settings_status.setWordWrap(True)
        self._settings_status.hide()

        save_btn = QPushButton("Save")
        save_btn.setObjectName("accent")
        save_btn.setMinimumHeight(44)
        save_btn.clicked.connect(self._save_settings_ui)

        back_btn = QPushButton("Back")
        back_btn.clicked.connect(lambda: self._show_panel(self._choice_widget))

        layout.addWidget(label)
        layout.addWidget(self._host_input)
        layout.addWidget(env_note)
        layout.addWidget(self._settings_status)
        layout.addWidget(save_btn)
        layout.addWidget(back_btn)
        return w

    def _set_settings_status(self, text: str, ok: bool):
        color = "#22c55e" if ok else "#ef4444"
        self._settings_status.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._settings_status.setText(text)
        self._settings_status.show()
        if ok:
            QTimer.singleShot(2000, self._settings_status.hide)

    def _save_settings_ui(self):
        raw = self._host_input.text().strip()
        host = normalize_host(raw) if raw else None
        if raw and host is None:
            self._set_settings_status("Invalid host. Use a hostname[:port] or a ws:// / wss:// URL.", False)
            return
        try:
            save_settings({"partykit_host": host})
        except OSError as e:
            self._set_settings_status(f"Couldn't save settings: {e.strerror or e}", False)
            return
        if host:
            self._host_input.setText(host)
        self._set_settings_status("Saved", True)

    def _show_panel(self, panel):
        for p in self._panels:
            p.setVisible(p is panel)
        if panel is self._viewer_widget:
            self._code_input.setFocus()
        self.adjustSize()

    def _copy_code(self):
        QApplication.clipboard().setText(self._generated_code)
        self._copy_btn.setText("✓")
        self._copy_btn.setStyleSheet("color: #22c55e; border-color: #22c55e;")
        QTimer.singleShot(1500, self._reset_copy_btn)

    def _reset_copy_btn(self):
        self._copy_btn.setText("⎘")
        self._copy_btn.setStyleSheet("")

    def _server_configured(self, error_label: QLabel) -> bool:
        if normalize_host(resolve_host() or ""):
            return True
        error_label.setText("Set the PartyKit host in Settings first")
        error_label.show()
        return False

    def _accept_host(self):
        if not self._server_configured(self._host_error):
            return
        self.role = "host"
        self.room_code = self._generated_code
        self.accept()

    def _accept_viewer(self):
        code = normalize_room_code(self._code_input.text())
        if code is None:
            self._viewer_error.setText("Enter a room code like ABCD-1234")
            self._viewer_error.show()
            return
        if not self._server_configured(self._viewer_error):
            return
        self.role = "viewer"
        self.room_code = code
        self.accept()


class SyncApp(QObject):
    """Glues the player to the PartyKit client. All state lives on the Qt GUI thread."""

    # Emitted from the network thread; queued onto this object's (GUI) thread.
    _net_message = pyqtSignal(object)
    _net_status = pyqtSignal(str, bool)

    def __init__(self, role_hint: str, room_code: str, player, client):
        super().__init__()
        self.role: str | None = None
        self._role_hint = role_hint
        self._room_code = room_code
        self.video_player = player
        self.party_client = client
        self.peer_id: str | None = None
        self._host_id: str | None = None
        self._peers: list[str] = []
        self._last_sync: SyncState | None = None
        self._last_host_seen = time.monotonic()
        self._host_disconnect_warned = False

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

        self._silence_timer = QTimer(self)
        self._silence_timer.setInterval(SILENCE_CHECK_INTERVAL_MS)
        self._silence_timer.timeout.connect(self._check_host_silence)

        self._sync_debounce = QTimer(self)
        self._sync_debounce.setSingleShot(True)
        self._sync_debounce.setInterval(SYNC_DEBOUNCE_MS)
        self._sync_debounce.timeout.connect(self._send_sync_state)

    def start(self):
        self.video_player.set_room_code(self._room_code)
        self.video_player.set_connection_status("Connecting…", False)
        self.video_player.show()

        self._net_message.connect(self._on_message)
        self._net_status.connect(self.video_player.set_connection_status)
        self.party_client.on_message = self._net_message.emit
        self.party_client.on_status = self._net_status.emit

        self.video_player.playRequested.connect(self._on_local_control)
        self.video_player.pauseRequested.connect(self._on_local_control)
        self.video_player.seekRequested.connect(self._on_local_control)
        self.video_player.fileLoaded.connect(self._on_file_loaded)
        self.video_player.transferRequested.connect(self._transfer_host)
        self.video_player.closing.connect(self.stop)

        # Provisional until the server's welcome confirms which role we actually got.
        self._apply_role(self._role_hint)
        self.party_client.start()

    def stop(self):
        for timer in (self._heartbeat_timer, self._silence_timer, self._sync_debounce):
            timer.stop()
        self.party_client.on_message = None
        self.party_client.on_status = None
        self.party_client.stop()

    # --- roles -------------------------------------------------------------

    def _apply_role(self, role: str):
        self.role = role
        if role == "host":
            self.video_player.set_host_mode()
            self._silence_timer.stop()
            self._heartbeat_timer.start()
            self._send_sync_state()
        else:
            self.video_player.set_viewer_mode()
            self._heartbeat_timer.stop()
            self._sync_debounce.stop()
            self._on_host_alive()  # restart the silence window and drop any stale warning
            self._silence_timer.start()
        self._refresh_transfer_targets()

    def _refresh_transfer_targets(self):
        peers = self._peers if self.role == "host" else []
        self.video_player.set_transfer_targets(
            [(f"Viewer {i + 1} · {peer[:6]}", peer) for i, peer in enumerate(peers)]
        )

    def _transfer_host(self, target_id: str):
        if self.role == "host" and target_id in self._peers:
            # Our role flips when the server confirms with host_changed.
            self.party_client.send_threadsafe({"type": "transfer_host", "targetId": target_id})

    # --- incoming ----------------------------------------------------------

    @pyqtSlot(object)
    def _on_message(self, data: dict):
        try:
            self._dispatch(data)
        except Exception:
            # An exception escaping a Qt slot makes PyQt abort the whole app.
            log.exception("Failed to handle message: %r", data)

    def _dispatch(self, data: dict):
        msg_type = data.get("type")

        if msg_type == "welcome":
            self.peer_id = data.get("peerId")
            self._host_id = data.get("hostId")
            peers = data.get("peers")
            self._peers = [p for p in peers if isinstance(p, str) and p != self.peer_id] \
                if isinstance(peers, list) else []
            self._apply_role("host" if data.get("role") == "host" else "viewer")
        elif msg_type == "peer_joined":
            peer = data.get("peerId")
            if isinstance(peer, str) and peer != self.peer_id and peer not in self._peers:
                self._peers.append(peer)
                self._refresh_transfer_targets()
            if self.role == "host":
                log.info("Viewer joined: %s", peer)
                self._send_sync_state()
        elif msg_type == "peer_left":
            peer = data.get("peerId")
            if peer in self._peers:
                self._peers.remove(peer)
                self._refresh_transfer_targets()
        elif msg_type == "host_changed":
            self._host_id = data.get("newHostId")
            if self._host_id == self.peer_id and self.role != "host":
                log.info("Promoted to host")
                self._apply_role("host")
            elif self._host_id != self.peer_id and self.role == "host":
                log.info("Host role moved to %s", self._host_id)
                self._apply_role("viewer")
        elif msg_type in ("sync", "heartbeat") and self.role == "viewer":
            if self._host_id and data.get("senderId") != self._host_id:
                return
            self._on_host_alive()
            sync = parse_sync(data)
            if sync is None:
                log.warning("Ignoring malformed %s: %r", msg_type, data)
                return
            self._apply_sync(sync, force=msg_type == "sync")
        elif msg_type == "error" and data.get("code") == "room_not_found":
            self._host_disconnect_warned = True  # keep the silence check from overwriting this
            self.video_player.show_warning("Room not found — waiting for the host to open it…")

    def _on_host_alive(self):
        self._last_host_seen = time.monotonic()
        if self._host_disconnect_warned:
            self._host_disconnect_warned = False
            self.video_player.clear_warning()

    def _check_host_silence(self):
        if self.role != "viewer" or self._host_disconnect_warned:
            return
        if time.monotonic() - self._last_host_seen > HOST_SILENCE_TIMEOUT_SEC:
            self._host_disconnect_warned = True
            self.video_player.show_warning("Host disconnected — waiting…")
            self.video_player.pause()

    def _apply_sync(self, sync: SyncState, force: bool):
        """force: explicit host action (always apply). Otherwise only correct real drift."""
        self._last_sync = sync
        self.video_player.update_host_status(sync.filename, sync.state, sync.video_time)
        if not sync.filename or self.video_player.loaded_file is None:
            return

        now = self.party_client.clock.now(time.time())
        target = expected_position(sync, now, self.video_player.get_duration())
        want_playing = sync.state == "playing"
        if not force and want_playing == self.video_player.is_playing() \
                and not needs_correction(self.video_player.get_current_time(), target):
            return

        if want_playing:
            self.video_player.play()
            self.video_player.seek_to(target)
        else:
            self.video_player.seek_to(target)
            self.video_player.pause()

    def _on_file_loaded(self):
        if self.role == "viewer":
            QTimer.singleShot(FILE_LOAD_SETTLE_MS, self._resync_after_load)

    def _resync_after_load(self):
        if self.role != "viewer":
            return
        if self._last_sync and self._last_sync.filename:
            self._apply_sync(self._last_sync, force=True)
        else:
            self.video_player.pause()  # nothing to follow yet

    # --- outgoing ----------------------------------------------------------

    def _on_local_control(self, *_):
        if self.role == "host":
            self._sync_debounce.start()

    def _state_message(self, msg_type: str) -> dict:
        loaded = self.video_player.loaded_file
        return {
            "type": msg_type,
            "state": "playing" if loaded and self.video_player.is_playing() else "paused",
            "videoTime": self.video_player.get_current_time() if loaded else 0.0,
            "wallClock": self.party_client.clock.now(time.time()),
            "filename": os.path.basename(loaded) if loaded else "",
        }

    def _send_sync_state(self):
        if self.role != "host" or self.video_player.loaded_file is None:
            return
        msg = self._state_message("sync")
        if self.party_client.send_threadsafe(msg):
            log.info("Sent: %s at %.1fs", msg["state"], msg["videoTime"])

    def _send_heartbeat(self):
        # Heartbeats carry full state so viewers can correct drift between explicit syncs.
        if self.role == "host":
            self.party_client.send_threadsafe(self._state_message("heartbeat"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    app = QApplication(sys.argv)

    dialog = RoleSelectDialog()
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    player = VideoPlayerWindow()
    client = PartyKitClient(dialog.room_code, dialog.role, generate_token())
    sync_app = SyncApp(dialog.role, dialog.room_code, player, client)
    sync_app.start()

    ret = app.exec()
    sync_app.stop()
    return ret


if __name__ == "__main__":
    sys.exit(main())
