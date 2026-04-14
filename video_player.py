import sys
import cv2
import numpy as np
import pygame
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QSlider, QLabel, QFileDialog)
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap


class VideoPlayerWindow(QMainWindow):
    playRequested = pyqtSignal()
    pauseRequested = pyqtSignal()
    seekRequested = pyqtSignal(float)
    positionChanged = pyqtSignal(float)
    stateChanged = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python Video Player - OpenCV")
        self.resize(800, 650)
        self.setMouseTracking(True)
        
        pygame.mixer.init()
        
        self._is_playing = False
        self._is_fullscreen = False
        self._video_path = None
        self._cap = None
        self._fps = 30
        self._total_frames = 0
        self._current_frame = 0
        self._audio_path = None

        self._setup_ui()
        
        print("[VideoPlayer] Init complete")
    
    def _setup_ui(self):
        centralWidget = QWidget()
        self.setCentralWidget(centralWidget)
        
        layout = QVBoxLayout(centralWidget)
        self._mainLayout = layout
        
        self.videoLabel = QLabel("No video loaded")
        self.videoLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.videoLabel.setMinimumSize(640, 360)
        self.videoLabel.setStyleSheet("background-color: black; color: white;")
        self.videoLabel.setMouseTracking(True)
        layout.addWidget(self.videoLabel, 1)

        controlsLayout = QHBoxLayout()
        self.openButton = QPushButton("Open")
        self.playButton = QPushButton("Play")
        self.pauseButton = QPushButton("Pause")
        self.fullscreenButton = QPushButton("Fullscreen")

        self.seekBackButton = QPushButton("<< 5s")
        self.seekFwdButton = QPushButton("5s >>")

        self.openButton.clicked.connect(self.open_file)
        self.playButton.clicked.connect(self.play)
        self.pauseButton.clicked.connect(self.pause)
        self.seekBackButton.clicked.connect(lambda: self.seek_relative(-5))
        self.seekFwdButton.clicked.connect(lambda: self.seek_relative(5))
        self.fullscreenButton.clicked.connect(self._toggle_fullscreen)

        controlsLayout.addWidget(self.openButton)
        controlsLayout.addWidget(self.seekBackButton)
        controlsLayout.addWidget(self.playButton)
        controlsLayout.addWidget(self.pauseButton)
        controlsLayout.addWidget(self.seekFwdButton)

        self.positionSlider = QSlider(Qt.Orientation.Horizontal)
        self.positionSlider.setRange(0, 100)
        self.positionSlider.sliderMoved.connect(self.set_position)
        controlsLayout.addWidget(self.positionSlider, 1)

        self.timeLabel = QLabel("00:00")
        controlsLayout.addWidget(self.timeLabel)
        controlsLayout.addWidget(self.fullscreenButton)

        self.controlsWidget = QWidget()
        self.controlsWidget.setLayout(controlsLayout)
        layout.addWidget(self.controlsWidget)

        self.statusLabel = QLabel("Ready - Open a video file")
        layout.addWidget(self.statusLabel)

        self.modeLabel = QLabel("Viewer mode — waiting for host")
        self.modeLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.modeLabel.setStyleSheet("color: #aaaaaa; font-style: italic;")
        self.modeLabel.hide()
        layout.addWidget(self.modeLabel)

        self.timer = QTimer()
        self.timer.timeout.connect(self._update_frame)

        self._hide_controls_timer = QTimer()
        self._hide_controls_timer.setSingleShot(True)
        self._hide_controls_timer.setInterval(2000)
        self._hide_controls_timer.timeout.connect(self._on_hide_controls_timeout)

        QApplication.instance().installEventFilter(self)
    
    def open_file(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", 
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv);;All Files (*)"
        )
        if filePath:
            self._load_video(filePath)
    
    def _extract_audio(self, video_path):
        import tempfile
        import os
        import subprocess
        
        tmp_dir = tempfile.gettempdir()
        audio_path = os.path.join(tmp_dir, "video_audio.mp3")
        
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "libmp3lame",
            "-ab", "192k", audio_path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                return audio_path
        except:
            pass
        return None
    
    def _load_video(self, filePath):
        self._video_path = filePath
        self._cap = cv2.VideoCapture(filePath)
        
        if not self._cap.isOpened():
            self.statusLabel.setText(f"Error: Cannot open {filePath}")
            return
        
        self._fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._current_frame = 0
        
        self._audio_path = self._extract_audio(filePath)
        if self._audio_path:
            try:
                pygame.mixer.music.load(self._audio_path)
                print(f"[VideoPlayer] Audio loaded: {self._audio_path}")
            except Exception as e:
                print(f"[VideoPlayer] Audio load error: {e}")
                self._audio_path = None
        else:
            print("[VideoPlayer] No audio extracted")
        
        print(f"[VideoPlayer] Loaded: {filePath}")
        print(f"[VideoPlayer] FPS: {self._fps}, Frames: {self._total_frames}")
        
        self.positionSlider.setRange(0, max(1, self._total_frames - 1))
        self.statusLabel.setText(f"Loaded: {filePath.split('/')[-1]}")
        
        self._show_frame()
        self.play()
    
    def _show_frame(self):
        if self._cap is None or not self._cap.isOpened():
            return
        
        ret, frame = self._cap.retrieve()
        if not ret:
            return
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(self.videoLabel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.videoLabel.setPixmap(scaled)
    
    def _format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
    
    def _update_frame(self):
        if self._cap is None or not self._is_playing:
            return
        
        ret, frame = self._cap.read()
        if not ret:
            self._current_frame = 0
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            if self._audio_path:
                pygame.mixer.music.stop()
            return
        
        self._current_frame = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
        self.positionSlider.setValue(self._current_frame)
        
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(self.videoLabel.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.videoLabel.setPixmap(scaled)
        
        current_sec = self._current_frame / self._fps
        self.timeLabel.setText(self._format_time(current_sec))
        
        self.positionChanged.emit(current_sec)
    
    def play(self):
        if self._cap is None:
            return
        
        if not self._is_playing:
            self._is_playing = True
            interval = int(1000 / max(1, self._fps))
            self.timer.start(interval)
            
            if self._audio_path:
                current_sec = self._current_frame / self._fps
                pygame.mixer.music.play(start=current_sec)
        
        self.playRequested.emit()
        self.stateChanged.emit("playing")
        print("[VideoPlayer] Play")
    
    def pause(self):
        self._is_playing = False
        self.timer.stop()
        
        if self._audio_path:
            pygame.mixer.music.pause()
        
        self.pauseRequested.emit()
        self.stateChanged.emit("paused")
        print("[VideoPlayer] Pause")
    
    def stop(self):
        self.pause()
        if self._cap:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self._show_frame()
        if self._audio_path:
            pygame.mixer.music.stop()
        self.stateChanged.emit("stopped")
    
    def set_position(self, frame_num):
        if self._cap is None:
            return
        
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        self._current_frame = frame_num
        self._show_frame()
        
        if self._audio_path and self._is_playing:
            seek_time = frame_num / self._fps
            pygame.mixer.music.play(start=seek_time)
        
        current_sec = frame_num / self._fps
        self.seekRequested.emit(current_sec)
    
    def seek_relative(self, delta_sec: float):
        new_time = self.get_current_time() + delta_sec
        new_time = max(0, min(new_time, self.get_duration()))
        self.seek_to(new_time)

    def seek_to(self, timestamp_sec):
        if self._cap is None:
            return
        
        frame_num = int(timestamp_sec * self._fps)
        self.set_position(frame_num)
    
    def get_current_time(self):
        return self._current_frame / self._fps if self._fps > 0 else 0
    
    def get_duration(self):
        return self._total_frames / self._fps if self._fps > 0 else 0
    
    def is_playing(self):
        return self._is_playing
    
    def set_viewer_mode(self):
        self.playButton.setEnabled(False)
        self.pauseButton.setEnabled(False)
        self.seekBackButton.setEnabled(False)
        self.seekFwdButton.setEnabled(False)
        self.positionSlider.setEnabled(False)
        self.modeLabel.show()

    def set_host_mode(self):
        self.playButton.setEnabled(True)
        self.pauseButton.setEnabled(True)
        self.seekBackButton.setEnabled(True)
        self.seekFwdButton.setEnabled(True)
        self.positionSlider.setEnabled(True)
        self.modeLabel.hide()

    def show_warning(self, text: str):
        self.statusLabel.setText(text)
        self.statusLabel.setStyleSheet("color: red;")

    def clear_warning(self):
        self.statusLabel.setText("Ready")
        self.statusLabel.setStyleSheet("")

    def _toggle_fullscreen(self):
        if not self._is_fullscreen:
            self.showFullScreen()
            self._mainLayout.setContentsMargins(0, 0, 0, 0)
            self._mainLayout.setSpacing(0)
            self.controlsWidget.hide()
            self.statusLabel.hide()
            self.modeLabel.hide()
            self._is_fullscreen = True
            self.fullscreenButton.setText("Exit Fullscreen")
        else:
            self.showNormal()
            self._mainLayout.setContentsMargins(-1, -1, -1, -1)
            self._mainLayout.setSpacing(-1)
            self.controlsWidget.show()
            self.statusLabel.show()
            if not self.playButton.isEnabled():
                self.modeLabel.show()
            self._is_fullscreen = False
            self.fullscreenButton.setText("Fullscreen")

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
        self.timer.stop()
        if self._cap:
            self._cap.release()
        pygame.mixer.music.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoPlayerWindow()
    window.show()
    sys.exit(app.exec())