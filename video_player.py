import sys
import vlc
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QSlider, QLabel,
                               QFileDialog, QMenu, QFrame, QStyle)
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QCursor


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
        layout.addWidget(self._copy_code_btn)

        layout.addStretch()

        self.optionsButton = QPushButton("⚙")
        self.optionsButton.setObjectName("titleBarBtn")
        self.optionsButton.setFixedSize(28, 28)
        self.optionsButton.setToolTip("Options")
        self._menu = QMenu(self)
        self._open_action = self._menu.addAction("Open Video…")
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
        QApplication.clipboard().setText(self._room_code_label.text())

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


class VideoPlayerWindow(QMainWindow):
    playRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    seekRequested = pyqtSignal(float)
    positionChanged = pyqtSignal(float)
    stateChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Video Sync")
        self.setMinimumSize(720, 480)
        self.resize(900, 600)
        self.setMouseTracking(True)

        self._is_fullscreen = False
        self._intended_playing = False
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

        QApplication.instance().installEventFilter(self)

        print("[VideoPlayer] Init complete")

    def _setup_ui(self):
        centralWidget = QWidget()
        self.setCentralWidget(centralWidget)

        layout = QVBoxLayout(centralWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._mainLayout = layout

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
        media = self._vlc.media_new(file_path)
        self._player.set_media(media)
        self._player.set_xwindow(int(self.videoFrame.winId()))
        duration_ms = self._get_duration_ms()
        self.positionSlider.setRange(0, max(1, duration_ms))
        self.statusLabel.setText(f"Loaded: {file_path.split('/')[-1]}")
        print(f"[VideoPlayer] Loaded: {file_path}")
        self.play()

    def _get_duration_ms(self):
        dur = self._player.get_length()
        return dur if dur > 0 else 0

    def _poll_position(self):
        pos_ms = self._player.get_time()
        if pos_ms < 0:
            return

        dur_ms = self._player.get_length()
        if dur_ms > 0 and self.positionSlider.maximum() != dur_ms:
            self.positionSlider.setRange(0, dur_ms)

        if not self.positionSlider._dragging:
            self.positionSlider.setValue(pos_ms)

        self.timeLabel.setText(self._format_time(pos_ms / 1000))
        self.positionChanged.emit(pos_ms / 1000)

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
        self.stateChanged.emit("playing")
        print("[VideoPlayer] Play")

    def pause(self):
        self._intended_playing = False
        self._player.set_pause(1)
        self.playPauseButton.setText("▶")
        self.pauseRequested.emit()
        self.stateChanged.emit("paused")
        print("[VideoPlayer] Pause")

    def stop(self):
        self._player.stop()
        self.stateChanged.emit("stopped")

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

    def set_viewer_mode(self):
        self.playPauseButton.setEnabled(False)
        self.seekBackButton.setEnabled(False)
        self.seekFwdButton.setEnabled(False)
        self.positionSlider.setEnabled(False)
        self.modeLabel.show()

    def set_host_mode(self):
        self.playPauseButton.setEnabled(True)
        self.seekBackButton.setEnabled(True)
        self.seekFwdButton.setEnabled(True)
        self.positionSlider.setEnabled(True)
        self.modeLabel.hide()

    def show_warning(self, text: str):
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet(
            "background-color: #111111; color: #ef4444; font-size: 11px; padding: 4px 12px;"
        )

    def clear_warning(self):
        self.statusLabel.setText("Ready")
        self.statusLabel.setStyleSheet(
            "background-color: #111111; color: #888888; font-size: 11px; padding: 4px 12px;"
        )

    def _toggle_fullscreen(self):
        if not self._is_fullscreen:
            self.showFullScreen()
            self._mainLayout.setContentsMargins(0, 0, 0, 0)
            self._mainLayout.setSpacing(0)
            self.titleBar.hide()
            self.controlsWidget.hide()
            self.statusLabel.hide()
            self.modeLabel.hide()
            self._is_fullscreen = True
            self.fullscreenButton.setText("⊠")
        else:
            self.showNormal()
            self._mainLayout.setContentsMargins(0, 0, 0, 0)
            self._mainLayout.setSpacing(0)
            self.titleBar.show()
            self.controlsWidget.show()
            self.statusLabel.show()
            if not self.playButton.isEnabled():
                self.modeLabel.show()
            self._is_fullscreen = False
            self.fullscreenButton.setText("⛶")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove and self._is_fullscreen:
            self.controlsWidget.show()
            self.statusLabel.show()
            self._hide_controls_timer.start()
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Left:
                self.seek_relative(-5)
                return True
            elif event.key() == Qt.Key.Key_Right:
                self.seek_relative(5)
                return True
            elif event.key() == Qt.Key.Key_F:
                self._toggle_fullscreen()
                return True
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

    def keyPressEvent(self, event):
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._player.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoPlayerWindow()
    window.show()
    sys.exit(app.exec())
