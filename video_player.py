import logging
import os
import sys
import vlc
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QSlider, QLabel,
                               QFileDialog, QMenu, QFrame, QStyle)
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut

log = logging.getLogger("player")


class ClickSlider(QSlider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), self.width()
            )
            self.setValue(val)
            self.sliderMoved.emit(val)
            self._dragging = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), self.width()
            )
            val = max(self.minimum(), min(self.maximum(), val))
            self.setValue(val)
            self.sliderMoved.emit(val)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class TitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(36)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(4)

        title = QLabel("Video Sync")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        self._room_code_label = QLabel("")
        self._room_code_label.setObjectName("roomCodeLabel")
        self._room_code_label.hide()
        layout.addWidget(self._room_code_label)

        self._copy_code_btn = QPushButton("⎘")
        self._copy_code_btn.setObjectName("titleBarBtn")
        self._copy_code_btn.setFixedSize(24, 24)
        self._copy_code_btn.setToolTip("Copy room code")
        self._copy_code_btn.hide()
        self._copy_code_btn.clicked.connect(self._on_copy_room_code)
        self._copy_feedback_timer = QTimer()
        self._copy_feedback_timer.timeout.connect(self._reset_copy_btn)
        layout.addWidget(self._copy_code_btn)

        self._conn_label = QLabel("")
        self._conn_label.setObjectName("connLabel")
        layout.addWidget(self._conn_label)

        layout.addStretch()

        self.optionsButton = QPushButton("⚙")
        self.optionsButton.setObjectName("titleBarBtn")
        self.optionsButton.setFixedSize(28, 28)
        self.optionsButton.setToolTip("Options")
        self._menu = QMenu(self)
        self._open_action = self._menu.addAction("Open Video…")
        self._transfer_menu = self._menu.addMenu("Transfer host to")
        self._transfer_menu.setEnabled(False)
        self.optionsButton.clicked.connect(self._show_menu)

        self.minButton = QPushButton("−")
        self.minButton.setObjectName("titleBarBtn")
        self.minButton.setFixedSize(28, 28)
        self.minButton.clicked.connect(parent.showMinimized)

        self.maxButton = QPushButton("□")
        self.maxButton.setObjectName("titleBarBtn")
        self.maxButton.setFixedSize(28, 28)
        self.maxButton.clicked.connect(self._toggle_maximize)

        self.closeButton = QPushButton("✕")
        self.closeButton.setObjectName("closeBtn")
        self.closeButton.setFixedSize(28, 28)
        self.closeButton.clicked.connect(parent.close)

        for btn in [self.optionsButton, self.minButton, self.maxButton, self.closeButton]:
            layout.addWidget(btn)

    def _on_copy_room_code(self):
        code = self._room_code_label.text()
        if not code:
            return
        QApplication.clipboard().setText(code)
        self._copy_code_btn.setText("✓")
        self._copy_code_btn.setStyleSheet("color: #22c55e;")
        self._copy_feedback_timer.start(1500)

    def _reset_copy_btn(self):
        self._copy_feedback_timer.stop()
        self._copy_code_btn.setText("⎘")
        self._copy_code_btn.setStyleSheet("")

    def _show_menu(self):
        pos = self.optionsButton.mapToGlobal(self.optionsButton.rect().bottomLeft())
        self._menu.exec(pos)

    def _toggle_maximize(self):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
            self.maxButton.setText("□")
        else:
            win.showMaximized()
            self.maxButton.setText("❐")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            diff = event.globalPosition().toPoint() - self._drag_pos
            self._drag_pos = event.globalPosition().toPoint()
            self.window().move(self.window().pos() + diff)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)


def _set_video_output(player, window_id: int):
    """Embed VLC output in a native window; 0 detaches."""
    if sys.platform == "win32":
        player.set_hwnd(window_id)
    elif sys.platform == "darwin":
        player.set_nsobject(window_id)
    else:
        player.set_xwindow(window_id)


class VideoPlayerWindow(QMainWindow):
    playRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    seekRequested = pyqtSignal(float)
    fileLoaded = pyqtSignal()
    transferRequested = pyqtSignal(str)
    closing = pyqtSignal()  # emitted before libvlc is released; stop anything that polls the player

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Video Sync")
        self.setMinimumSize(720, 480)
        self.resize(900, 600)
        self.setMouseTracking(True)

        self._is_fullscreen = False
        self._intended_playing = False
        self._controls_enabled = True
        self._loaded_file = None
        self._vlc = vlc.Instance()
        self._player = self._vlc.media_player_new()

        self._setup_ui()
        self._apply_styles()

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._poll_position)
        self._poll_timer.start()

        self._hide_controls_timer = QTimer()
        self._hide_controls_timer.setSingleShot(True)
        self._hide_controls_timer.setInterval(2000)
        self._hide_controls_timer.timeout.connect(self._on_hide_controls_timeout)

        # App-wide filter only to reveal fullscreen controls on mouse move; it never consumes events.
        QApplication.instance().installEventFilter(self)
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        # Window-scoped shortcuts, so text fields in dialogs keep their arrow keys and letters.
        for key, handler in (
            (Qt.Key.Key_Left, lambda: self._shortcut_seek(-5)),
            (Qt.Key.Key_Right, lambda: self._shortcut_seek(5)),
            (Qt.Key.Key_F, self._toggle_fullscreen),
        ):
            QShortcut(QKeySequence(key), self).activated.connect(handler)

    def _shortcut_seek(self, delta_sec: float):
        if self._controls_enabled:
            self.seek_relative(delta_sec)

    def _setup_ui(self):
        centralWidget = QWidget()
        self.setCentralWidget(centralWidget)

        layout = QVBoxLayout(centralWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.titleBar = TitleBar(self)
        self.titleBar._open_action.triggered.connect(self.open_file)
        layout.addWidget(self.titleBar)

        self.videoFrame = QFrame()
        self.videoFrame.setObjectName("videoFrame")
        self.videoFrame.setMinimumSize(640, 360)
        self.videoFrame.setMouseTracking(True)
        self.videoFrame.setStyleSheet("background-color: #000000;")
        layout.addWidget(self.videoFrame, 1)

        controlsLayout = QHBoxLayout()
        controlsLayout.setContentsMargins(12, 8, 12, 8)
        controlsLayout.setSpacing(8)

        self.playPauseButton = QPushButton("▶")
        self.playPauseButton.setObjectName("playBtn")
        self.seekBackButton = QPushButton("« 5s")
        self.seekFwdButton = QPushButton("5s »")
        self.fullscreenButton = QPushButton("⛶")
        self.fullscreenButton.setFixedSize(34, 34)
        self.fullscreenButton.setToolTip("Fullscreen (F)")

        self.playPauseButton.clicked.connect(self._toggle_play_pause)
        self.seekBackButton.clicked.connect(lambda: self.seek_relative(-5))
        self.seekFwdButton.clicked.connect(lambda: self.seek_relative(5))
        self.fullscreenButton.clicked.connect(self._toggle_fullscreen)

        controlsLayout.addWidget(self.seekBackButton)
        controlsLayout.addWidget(self.playPauseButton)
        controlsLayout.addWidget(self.seekFwdButton)

        self.positionSlider = ClickSlider(Qt.Orientation.Horizontal)
        self.positionSlider.setRange(0, 0)
        self.positionSlider.sliderMoved.connect(self._on_slider_moved)
        controlsLayout.addWidget(self.positionSlider, 1)

        self.timeLabel = QLabel("00:00")
        self.timeLabel.setObjectName("timeLabel")
        controlsLayout.addWidget(self.timeLabel)
        controlsLayout.addWidget(self.fullscreenButton)

        self.controlsWidget = QWidget()
        self.controlsWidget.setObjectName("controlsBar")
        self.controlsWidget.setLayout(controlsLayout)
        layout.addWidget(self.controlsWidget)

        self.statusLabel = QLabel("Ready — open a video file via ⚙")
        self.statusLabel.setObjectName("statusBar")
        layout.addWidget(self.statusLabel)

        self.modeLabel = QLabel("Viewer mode — waiting for host")
        self.modeLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.modeLabel.setObjectName("modeLabel")
        self.modeLabel.hide()
        layout.addWidget(self.modeLabel)

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0d0d0d;
            }
            QWidget {
                background-color: #0d0d0d;
                color: #ffffff;
                font-family: system-ui, sans-serif;
                font-size: 13px;
            }
            #titleBar {
                background-color: #1a1a1a;
                border-bottom: 1px solid #2a2a2a;
            }
            #titleLabel {
                color: #ffffff;
                font-weight: 600;
                font-size: 13px;
                background: transparent;
            }
            #roomCodeLabel {
                color: #7c3aed;
                font-family: monospace;
                font-size: 12px;
                font-weight: 600;
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 2px 8px;
                margin-left: 8px;
            }
            #connLabel {
                color: #888888;
                font-size: 11px;
                background: transparent;
                margin-left: 8px;
            }
            #titleBarBtn {
                background-color: transparent;
                color: #aaaaaa;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                padding: 0;
            }
            #titleBarBtn:hover {
                background-color: #2a2a2a;
                color: #ffffff;
            }
            #closeBtn {
                background-color: transparent;
                color: #aaaaaa;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                padding: 0;
            }
            #closeBtn:hover {
                background-color: #ef4444;
                color: #ffffff;
            }
            #controlsBar {
                background-color: #1a1a1a;
                border-top: 1px solid #2a2a2a;
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
            QPushButton:disabled {
                color: #555555;
                background-color: #1e1e1e;
            }
            #playBtn {
                background-color: #7c3aed;
                font-weight: 600;
            }
            #playBtn:hover {
                background-color: #6d28d9;
            }
            #playBtn:disabled {
                background-color: #3b1f6e;
                color: #7a6a9a;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #2a2a2a;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #7c3aed;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 12px;
                background: #7c3aed;
                border-radius: 6px;
                margin: -4px 0;
            }
            QSlider::handle:horizontal:hover {
                background: #9d65f5;
            }
            QSlider::handle:horizontal:disabled {
                background: #444444;
            }
            QSlider::groove:horizontal:disabled {
                background: #1e1e1e;
            }
            QSlider::sub-page:horizontal:disabled {
                background: #333333;
            }
            #timeLabel {
                color: #888888;
                font-family: monospace;
                font-size: 12px;
                background: transparent;
                min-width: 40px;
            }
            #statusBar {
                background-color: #111111;
                color: #888888;
                font-size: 11px;
                padding: 4px 12px;
                border-top: 1px solid #1e1e1e;
            }
            #modeLabel {
                background-color: #111111;
                color: #888888;
                font-size: 11px;
                font-style: italic;
                padding: 4px 12px;
            }
            QMenu {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                color: #ffffff;
                padding: 4px;
                border-radius: 6px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2a2a2a;
            }
        """)

    def open_file(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv);;All Files (*)"
        )
        if filePath:
            self._load_video(filePath)

    def _load_video(self, file_path):
        self._loaded_file = file_path
        media = self._vlc.media_new(file_path)
        self._player.set_media(media)
        self._attach_video_output()
        self.positionSlider.setRange(0, max(1, self._player.get_length()))
        self.statusLabel.setText(f"Loaded: {os.path.basename(file_path)}")
        log.info("Loaded: %s", file_path)
        self.fileLoaded.emit()
        self.play()

    def _attach_video_output(self):
        _set_video_output(self._player, int(self.videoFrame.winId()))

    @property
    def loaded_file(self) -> str | None:
        return self._loaded_file

    def _poll_position(self):
        if self._intended_playing and self._player.get_state() == vlc.State.Ended:
            self.pause()  # flips intent and emits pauseRequested, so a host broadcasts "paused"

        pos_ms = self._player.get_time()
        if pos_ms < 0:
            return

        dur_ms = self._player.get_length()
        if dur_ms > 0 and self.positionSlider.maximum() != dur_ms:
            self.positionSlider.setRange(0, dur_ms)

        if not self.positionSlider._dragging:
            self.positionSlider.setValue(max(0, min(pos_ms, self.positionSlider.maximum())))

        self.timeLabel.setText(self._format_time(pos_ms / 1000))

    def _on_slider_moved(self, position_ms):
        self._player.set_time(position_ms)
        self.seekRequested.emit(position_ms / 1000)

    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

    def _toggle_play_pause(self):
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def play(self):
        if self._player.get_media() is None:
            return
        self._intended_playing = True
        self._player.play()
        self.playPauseButton.setText("⏸")
        self.playRequested.emit()

    def pause(self):
        self._intended_playing = False
        self._player.set_pause(1)
        self.playPauseButton.setText("▶")
        self.pauseRequested.emit()

    def seek_to(self, timestamp_sec):
        self._player.set_time(int(timestamp_sec * 1000))
        self.seekRequested.emit(timestamp_sec)

    def seek_relative(self, delta_sec: float):
        new_time = self.get_current_time() + delta_sec
        new_time = max(0, min(new_time, self.get_duration()))
        self.seek_to(new_time)

    def get_current_time(self):
        t = self._player.get_time()
        return t / 1000.0 if t >= 0 else 0.0

    def get_duration(self):
        d = self._player.get_length()
        return d / 1000.0 if d > 0 else 0.0

    def is_playing(self):
        return self._intended_playing

    def set_room_code(self, code: str):
        self.titleBar._room_code_label.setText(code)
        self.titleBar._room_code_label.show()
        self.titleBar._copy_code_btn.show()

    def _set_controls_enabled(self, enabled: bool):
        self._controls_enabled = enabled
        for w in (self.playPauseButton, self.seekBackButton, self.seekFwdButton, self.positionSlider):
            w.setEnabled(enabled)
        self.modeLabel.setVisible(not enabled and not self._is_fullscreen)

    def set_viewer_mode(self):
        self._set_controls_enabled(False)

    def set_host_mode(self):
        self._set_controls_enabled(True)

    def set_connection_status(self, text: str, ok: bool):
        color = "#22c55e" if ok else "#f59e0b"
        self.titleBar._conn_label.setText(f"<span style='color:{color}'>●</span> {text}")

    def set_transfer_targets(self, targets: list[tuple[str, str]]):
        """targets: (label, peer_id) pairs; empty disables the menu."""
        menu = self.titleBar._transfer_menu
        menu.clear()
        for label, peer_id in targets:
            menu.addAction(label).triggered.connect(lambda _=False, p=peer_id: self.transferRequested.emit(p))
        menu.setEnabled(bool(targets))

    def _set_status(self, text: str, color: str):
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(
            f"background-color: #111111; color: {color}; font-size: 11px; padding: 4px 12px;"
        )

    def update_host_status(self, filename: str, state: str, video_time: float):
        if not filename:
            self._set_status("Host has no video open", "#cccccc")
            self.modeLabel.setText("Viewer mode  ·  waiting for host")
            return
        state_str = "Playing" if state == "playing" else "Paused"
        self._set_status(f"Host: {filename}  ·  {self._format_time(video_time)}  ·  {state_str}", "#cccccc")
        self.modeLabel.setText(f"Viewer mode  ·  host is {state_str.lower()}")

    def show_warning(self, text: str):
        self._set_status(text, "#ef4444")

    def clear_warning(self):
        self._set_status("Ready", "#888888")

    def _toggle_fullscreen(self):
        if not self._is_fullscreen:
            self.showFullScreen()
            self.titleBar.hide()
            self.controlsWidget.hide()
            self.statusLabel.hide()
            self.modeLabel.hide()
            self._is_fullscreen = True
            self.fullscreenButton.setText("⊠")
        else:
            self.showNormal()
            self.titleBar.show()
            self.controlsWidget.show()
            self.statusLabel.show()
            self.modeLabel.setVisible(not self._controls_enabled)
            self._is_fullscreen = False
            self.fullscreenButton.setText("⛶")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove and self._is_fullscreen:
            self.controlsWidget.show()
            self.statusLabel.show()
            self._hide_controls_timer.start()
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        if self._is_fullscreen:
            self.controlsWidget.show()
            self.statusLabel.show()
            self._hide_controls_timer.start()
        super().mouseMoveEvent(event)

    def _on_hide_controls_timeout(self):
        if self._is_fullscreen:
            self.controlsWidget.hide()
            self.statusLabel.hide()

    def closeEvent(self, event):
        self.closing.emit()
        self._loaded_file = None
        self._poll_timer.stop()
        self._hide_controls_timer.stop()
        QApplication.instance().removeEventFilter(self)
        # Release once and drop the references: a second closeEvent must not double-free libvlc objects.
        player, self._player = self._player, None
        instance, self._vlc = self._vlc, None
        if player:
            for step in (lambda: _set_video_output(player, 0), player.stop,
                         lambda: player.set_media(None), player.release):
                try:
                    step()
                except Exception:
                    pass
        if instance:
            try:
                instance.release()
            except Exception:
                pass
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoPlayerWindow()
    window.show()
    sys.exit(app.exec())
