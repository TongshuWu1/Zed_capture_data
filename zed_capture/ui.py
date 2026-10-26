"""Desktop capture workspace and media library."""
import os
import subprocess
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, QSize, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap, QIcon, QVector3D
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QSplitter, QComboBox,
                               QListWidget, QListWidgetItem, QSlider, QCheckBox,
                               QFileDialog, QGroupBox)
import OpenGL
# The SDK's Windows installer supplies an optional accelerate wheel built for
# NumPy 1.x, while pyzed 5.3 requires NumPy 2.x. Use PyOpenGL's compatible path.
OpenGL.USE_ACCELERATE = False
import pyqtgraph.opengl as gl

from .camera import CameraWorker, ExportWorker
from .sdk import sdk_root
from .storage import list_media
from .config import (DEFAULT_RESOLUTION, DEFAULT_FPS, DEFAULT_DEPTH_MODE,
                     DEFAULT_CAPTURE_PROFILE, CAPTURE_PROFILES)


STYLE = """QWidget { background:#101720; color:#dfe8f3; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#101720; }
QLabel#title { font-size:25px; font-weight:700; color:#f3f8ff; }
QLabel#muted { color:#91a3b8; }
QLabel#banner { background:#192c3d; color:#bcdef7; padding:10px; border-radius:6px; }
QPushButton { background:#243244; border:1px solid #34465b; padding:9px 13px; border-radius:6px; }
QPushButton:hover { background:#30435a; }
QPushButton:disabled { color:#637285; background:#1b2531; border-color:#263340; }
QPushButton#primary { background:#187bb9; border-color:#309bdc; color:white; font-weight:600; }
QPushButton#record { background:#833b43; border-color:#a8515d; color:white; }
QComboBox { padding:7px; background:#1b2735; border:1px solid #34465b; border-radius:5px; }
QComboBox QAbstractItemView { background:#1b2735; selection-background-color:#187bb9; }
QListWidget { background:#141e2a; border:1px solid #293a4e; border-radius:6px; }
QListWidget::item { padding:9px; border-bottom:1px solid #243244; }
QListWidget::item:selected { background:#214762; }
QGroupBox { border:1px solid #293a4e; border-radius:7px; margin-top:14px; padding-top:15px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; color:#a6bed7; }
QSlider::groove:horizontal { height:5px; background:#30435a; border-radius:2px; }
QSlider::handle:horizontal { background:#53b7ec; width:12px; margin:-4px 0; border-radius:5px; }
QSplitter::handle { background:#26374a; }
QToolTip { background:#293a4e; color:white; border:1px solid #52708f; }
"""


class ImageView(QLabel):
    def __init__(self, placeholder):
        super().__init__(placeholder)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 120)
        self.setStyleSheet("background:#090f16; color:#8297ad; border-radius:5px;")
        self.original = None

    def set_array(self, bgra):
        array = np.ascontiguousarray(bgra)
        fmt = QImage.Format.Format_ARGB32 if array.shape[2] == 4 else QImage.Format.Format_BGR888
        image = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], fmt).copy()
        self.original = QPixmap.fromImage(image)
        self.redraw()

    def set_file(self, path):
        pixmap = QPixmap(str(path))
        self.original = pixmap if not pixmap.isNull() else None
        self.redraw()

    def clear_view(self, text):
        self.original = None
        self.clear()
        self.setText(text)

    def redraw(self):
        if self.original is not None:
            self.setPixmap(self.original.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.redraw()


class CloudView(gl.GLViewWidget):
    """SDK XYZRGBA point cloud; rotate / pan / zoom like Depth Viewer."""
    def __init__(self):
        super().__init__()
        self.setBackgroundColor("#090f16")
        self.setMinimumSize(320, 220)
        self.points = gl.GLScatterPlotItem(pos=np.zeros((0, 3)), size=2, pxMode=True)
        self.points.setGLOptions("opaque")
        self.addItem(self.points)
        self.grid = gl.GLGridItem()
        self.grid.setSize(20, 20)
        self.grid.setSpacing(1, 1)
        self.grid.translate(0, 5, -1)
        self.grid.setVisible(False)
        self.addItem(self.grid)
        self.xyz = self.rgba = None
        self.lidar = False
        self.capture_profile = DEFAULT_CAPTURE_PROFILE
        self.home()

    def home(self):
        profile = CAPTURE_PROFILES[self.capture_profile]
        self.opts["center"] = QVector3D(0, profile["view_center"], 0)
        self.setCameraPosition(distance=profile["view_distance"], elevation=8, azimuth=-90)
        self.update()

    def set_profile(self, profile):
        if profile != self.capture_profile:
            self.capture_profile = profile
            self.home()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.RightButton:
            position = event.position()
            if hasattr(self, "mousePos"):
                delta = position - self.mousePos
                self.pan(delta.x(), delta.y(), 0, relative="view")
            self.mousePos = position
            return
        super().mouseMoveEvent(event)

    def set_cloud(self, xyz, rgba):
        self.xyz, self.rgba = xyz, rgba
        # SDK Y-up / forward -Z -> pyqtgraph Z-up / forward +Y.
        pos = xyz[:, [0, 2, 1]].copy()
        pos[:, 1] *= -1
        colors = rgba
        if self.lidar and len(xyz):
            profile = CAPTURE_PROFILES[self.capture_profile]
            t = np.clip((-xyz[:, 2] - profile["depth_min"]) /
                        (profile["depth_max"] - profile["depth_min"]), 0, 1)
            colors = np.column_stack((np.clip(1.5 - abs(4*t-3), 0, 1),
                                       np.clip(1.5 - abs(4*t-2), 0, 1),
                                       np.clip(1.5 - abs(4*t-1), 0, 1), np.ones(len(t))))
        self.points.setData(pos=pos, color=colors, size=2, pxMode=True)

    def clear_cloud(self):
        self.xyz = self.rgba = None
        self.points.setData(pos=np.zeros((0, 3)))


def button(text, callback, name=None):
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.clicked.connect(callback)
    return result


class MainWindow(QMainWindow):
    def __init__(self, data_root: Path, autoconnect=True):
        super().__init__()
        self.data_root = data_root.resolve()
        for category in ("photos", "recordings", "logs"):
            (self.data_root / category).mkdir(parents=True, exist_ok=True)
        self.setWindowTitle("ZED Capture")
        self.resize(1440, 940)
        self.setMinimumSize(1050, 720)
        self.setStyleSheet(STYLE)
        self.state = {"source": None, "recording": False, "paused": False}
        self.selected = None
        self.busy = False
        self.exporter = None
        self.pending_native = None
        self.pending_still = None
        self.pending_capture = None
        self.worker = CameraWorker(self.data_root)
        self.worker.event.connect(self.on_event)
        self.build_ui()
        self.refresh_library()
        self.update_controls()
        self.worker.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_frame)
        self.timer.start(50)
        if autoconnect:
            QTimer.singleShot(400, self.connect_camera)

    def build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        heading = QHBoxLayout()
        title = QLabel("ZED Capture")
        title.setObjectName("title")
        heading.addWidget(title)
        subtitle = QLabel("Stereo photos  /  SVO video  /  3D review")
        subtitle.setObjectName("muted")
        heading.addWidget(subtitle)
        heading.addStretch()
        heading.addWidget(button("Open data folder", lambda: self.open_folder(self.data_root)))
        root.addLayout(heading)
        bar = QHBoxLayout()
        self.resolution = QComboBox()
        self.resolution.addItems(["HD2K", "HD1080", "HD720", "VGA"])
        self.resolution.setCurrentText(DEFAULT_RESOLUTION)
        self.resolution.setToolTip("Resolution applies when connecting the live camera.")
        self.fps = QComboBox()
        self.fps.addItems(["15", "30", "60"])
        self.fps.setCurrentText(str(DEFAULT_FPS))
        self.depth_mode = QComboBox()
        self.depth_mode.addItems(["NEURAL_PLUS", "NEURAL", "NEURAL_LIGHT"])
        self.depth_mode.setCurrentText(DEFAULT_DEPTH_MODE)
        for label, widget in (("Resolution", self.resolution), ("FPS", self.fps), ("Depth", self.depth_mode)):
            bar.addWidget(QLabel(label))
            bar.addWidget(widget)
        self.connect_btn = button("Connect live", self.connect_camera)
        self.disconnect_btn = button("Disconnect", self.disconnect)
        self.native_btn = button("ZED Depth Viewer ↗", self.open_native)
        self.native_btn.setToolTip("Opens the actual StereoLabs app. Live camera access is handed over to it.")
        bar.addWidget(self.connect_btn)
        bar.addWidget(self.disconnect_btn)
        bar.addStretch()
        bar.addWidget(self.native_btn)
        root.addLayout(bar)
        tuning = QHBoxLayout()
        tuning.addWidget(QLabel("Capture profile"))
        self.profile = QComboBox()
        for key, settings in CAPTURE_PROFILES.items():
            self.profile.addItem(settings["label"], key)
        self.profile.setCurrentIndex(self.profile.findData(DEFAULT_CAPTURE_PROFILE))
        self.profile.setToolTip("Close-up shows depth from 0.2–2 m. General shows 0.2–20 m. Apply tuning to change the active source.")
        tuning.addWidget(self.profile)
        self.wb_auto = QCheckBox("Auto white balance")
        self.exposure_auto = QCheckBox("Auto exposure / gain")
        self.center_metering = QCheckBox("Meter center")
        self.center_metering.setToolTip("Exposure uses the center 60% of the image. Keep the close-up subject there, or uncheck for full-frame metering.")
        for control in (self.wb_auto, self.exposure_auto, self.center_metering):
            control.setChecked(True)
            tuning.addWidget(control)
        tuning.addStretch()
        self.apply_tuning_btn = button("Apply tuning", self.apply_tuning)
        self.apply_tuning_btn.setToolTip("Apply auto controls live. Changing the depth profile reopens the source. Recorded image colors cannot be changed.")
        tuning.addWidget(self.apply_tuning_btn)
        root.addLayout(tuning)
        self.banner = QLabel("Starting the ZED SDK…")
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        root.addWidget(self.banner)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 4, 0)
        library_header = QHBoxLayout()
        library_header.addWidget(QLabel("SAVED MEDIA"))
        library_header.addStretch()
        library_header.addWidget(button("↻", self.refresh_library))
        side.addLayout(library_header)
        self.filter = QComboBox()
        self.filter.addItems(["All media", "Photos", "Videos"])
        self.filter.currentIndexChanged.connect(self.refresh_library)
        side.addWidget(self.filter)
        self.library = QListWidget()
        self.library.setIconSize(QSize(92, 56))
        self.library.currentItemChanged.connect(self.select_media)
        self.library.itemDoubleClicked.connect(lambda _: self.review_svo())
        side.addWidget(self.library, 1)
        self.meta_label = QLabel("Your captures will appear here.\nDouble-click an item to review its SVO in 3D.")
        self.meta_label.setObjectName("muted")
        self.meta_label.setWordWrap(True)
        self.meta_label.setMinimumHeight(60)
        side.addWidget(self.meta_label)
        self.review_btn = button("Review selected SVO", self.review_svo)
        self.export_btn = button("Export selected video to MP4", self.export_mp4)
        self.folder_btn = button("Open selected capture folder", self.open_selected_folder)
        side.addWidget(self.review_btn)
        side.addWidget(self.export_btn)
        side.addWidget(self.folder_btn)
        side.addWidget(button("Open another SVO…", self.open_svo_file))
        splitter.addWidget(sidebar)
        workspace = QWidget()
        views = QVBoxLayout(workspace)
        views.setContentsMargins(4, 0, 0, 0)
        image_row = QHBoxLayout()
        self.color = ImageView("Connect the camera to see color")
        self.depth = ImageView("Depth preview")
        for title, view in (("COLOR / LEFT", self.color), ("DEPTH", self.depth)):
            box = QGroupBox(title)
            layout = QVBoxLayout(box)
            layout.addWidget(view)
            image_row.addWidget(box)
        views.addLayout(image_row, 2)
        cloud_box = QGroupBox("3D POINT CLOUD")
        cloud_layout = QVBoxLayout(cloud_box)
        cloud_tools = QHBoxLayout()
        hint = QLabel("Left drag: orbit   ·   Right drag: pan   ·   Scroll: zoom")
        hint.setObjectName("muted")
        cloud_tools.addWidget(hint)
        cloud_tools.addStretch()
        self.lidar = QCheckBox("Depth colors")
        self.lidar.toggled.connect(self.set_lidar)
        cloud_tools.addWidget(self.lidar)
        self.grid_checkbox = QCheckBox("Grid (1 m)")
        self.grid_checkbox.toggled.connect(lambda value: self.cloud.grid.setVisible(value))
        cloud_tools.addWidget(self.grid_checkbox)
        cloud_tools.addWidget(button("Reset view", lambda: self.cloud.home()))
        cloud_layout.addLayout(cloud_tools)
        self.cloud = CloudView()
        cloud_layout.addWidget(self.cloud, 1)
        confidence = QHBoxLayout()
        confidence.addWidget(QLabel("Depth confidence"))
        self.confidence = QSlider(Qt.Orientation.Horizontal)
        self.confidence.setRange(1, 100)
        self.confidence.setValue(95)
        self.confidence.setToolTip("Lower values filter out more uncertain depth points.")
        self.confidence_label = QLabel("95")
        self.confidence.valueChanged.connect(lambda value: self.confidence_label.setText(str(value)))
        self.confidence.sliderReleased.connect(lambda: self.worker.submit("confidence", value=self.confidence.value()))
        confidence.addWidget(self.confidence, 1)
        confidence.addWidget(self.confidence_label)
        cloud_layout.addLayout(confidence)
        views.addWidget(cloud_box, 3)
        playback = QHBoxLayout()
        self.play_btn = button("Play", lambda: self.worker.submit("pause"))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.sliderReleased.connect(lambda: self.worker.submit("seek", frame=self.seek.value()))
        self.position = QLabel("Live")
        playback.addWidget(self.play_btn)
        playback.addWidget(self.seek, 1)
        playback.addWidget(self.position)
        views.addLayout(playback)
        splitter.addWidget(workspace)
        splitter.setSizes([310, 1090])
        root.addWidget(splitter, 1)
        capture = QHBoxLayout()
        self.return_live_btn = button("← Back to live", self.connect_camera, "primary")
        self.return_live_btn.setMinimumHeight(45)
        self.return_live_btn.setShortcut("Ctrl+L")
        self.return_live_btn.setToolTip("Return from saved media to the live camera (Ctrl+L).")
        capture.addWidget(self.return_live_btn)
        self.shutter = button("Take photo + SVO", self.take_photo, "primary")
        self.shutter.setMinimumHeight(45)
        self.shutter.setToolTip("Save a stereo photo, depth, point cloud and matching one-frame SVO.")
        self.record_btn = button("●  Start video recording", self.toggle_record, "record")
        self.record_btn.setMinimumHeight(45)
        capture.addWidget(self.shutter)
        capture.addWidget(self.record_btn)
        self.stats = QLabel("Camera disconnected")
        self.stats.setObjectName("muted")
        capture.addStretch()
        capture.addWidget(self.stats)
        root.addLayout(capture)
        self.setCentralWidget(central)

    def set_busy(self, text):
        self.busy = True
        self.banner.setText(text)
        self.update_controls()

    def connect_camera(self):
        if not self.worker.isRunning():
            self.banner.setText("The camera worker is unavailable. Check data/logs/app.log, then restart the app.")
            return
        self.pending_still = None
        self.library.clearSelection()
        self.clear_views()
        self.set_busy("Connecting to the live camera…")
        self.worker.submit("open", resolution=self.resolution.currentText(),
                           fps=int(self.fps.currentText()), depth_mode=self.depth_mode.currentText(),
                           profile=self.profile.currentData(), **self.camera_control_choices())

    def camera_control_choices(self):
        return {"auto_white_balance": self.wb_auto.isChecked(),
                "auto_exposure": self.exposure_auto.isChecked(),
                "center_metering": self.center_metering.isChecked()}

    def apply_tuning(self):
        if self.busy or self.state.get("recording"):
            return
        if self.state.get("source") == "svo":
            self.load_svo(Path(self.state["path"]))
        elif (self.state.get("source") != "live" or
              self.state.get("capture_profile") != self.profile.currentData()):
            self.connect_camera()
        else:
            self.set_busy("Applying auto camera controls and allowing them to settle…")
            self.worker.submit("camera_settings", **self.camera_control_choices())

    def disconnect(self):
        self.set_busy("Finalizing files and releasing the camera…")
        self.worker.submit("disconnect")

    def take_photo(self):
        self.start_capture("photo")

    def start_capture(self, action):
        if self.busy or not self.worker.isRunning():
            return
        if self.state.get("source") != "live":
            # Wait for the first fresh live frame before capturing. A reviewed
            # SVO must never be accidentally used as the new capture's source.
            self.pending_capture = action
            self.connect_camera()
            return
        self.execute_capture(action)

    def execute_capture(self, action):
        self.set_busy("Saving full-resolution photo + lossless SVO…" if action == "photo"
                      else "Starting lossless SVO video recording…")
        self.worker.submit(action)

    def toggle_record(self):
        if self.state["recording"]:
            self.set_busy("Finalizing SVO recording…")
            self.worker.submit("stop_record")
        else:
            self.start_capture("record")

    def clear_views(self):
        self.color.clear_view("Waiting for color…")
        self.depth.clear_view("Waiting for depth…")
        self.cloud.clear_cloud()

    def on_event(self, kind, payload):
        if kind == "ready":
            self.banner.setText(f"ZED SDK {payload['sdk']} ready. Connect the camera to begin.")
            self.update_controls()
        elif kind == "notice":
            self.banner.setText(str(payload))
        elif kind == "error":
            self.pending_capture = None
            self.busy = False
            self.banner.setText("Error: " + str(payload))
            self.update_controls()
        elif kind == "saved":
            self.busy = False
            self.refresh_library()
            self.banner.setText(f"Saved to {payload}")
            self.update_controls()
        elif kind == "state":
            self.busy = self.pending_capture is not None
            self.state = payload
            source = payload.get("source")
            if source == "live":
                self.cloud.set_profile(payload.get("capture_profile", DEFAULT_CAPTURE_PROFILE))
                self.stats.setText(f"{payload['model']} · {payload['resolution'][0]}×{payload['resolution'][1]} · {payload['depth_mode']}")
                if not payload["recording"]:
                    controls = payload.get("camera_controls", {})
                    wb = "on" if controls.get("whitebalance_auto") else "off"
                    ae = "on" if controls.get("aec_agc") else "off"
                    label = CAPTURE_PROFILES[payload.get("capture_profile", DEFAULT_CAPTURE_PROFILE)]["label"]
                    self.banner.setText(f"Live · {label} · Auto WB {wb} · Auto exposure {ae} · Full-resolution PNG + lossless SVO.")
                else:
                    self.banner.setText("Recording SVO · Stop recording to finalize the file. Photo capture is available after stopping.")
            elif source == "svo":
                self.cloud.set_profile(payload.get("capture_profile", DEFAULT_CAPTURE_PROFILE))
                self.banner.setText(f"SVO review · {Path(payload['path']).name} · Depth and 3D are recomputed from stereo data.")
                self.stats.setText(f"{payload['model']} · {payload['frames']} recorded frames")
                self.seek.setRange(0, max(0, payload["frames"] - 1))
            else:
                self.stats.setText("Camera disconnected")
            self.update_controls()
            if not source and self.pending_still is not None:
                media, self.pending_still = self.pending_still, None
                self.color.set_file(media["folder"] / "left.png")
                self.depth.set_file(media["folder"] / "depth_preview.png")
                self.cloud.clear_cloud()
                self.banner.setText("Saved photo preview · Click Review selected SVO to load its 3D point cloud.")
            if not source and self.pending_native is not None:
                args, self.pending_native = self.pending_native, None
                self.launch_native(args)

    def poll_frame(self):
        frame = self.worker.take_latest()
        if frame is None:
            return
        self.color.set_array(frame["left"])
        self.depth.set_array(frame["depth"])
        self.cloud.set_cloud(frame["xyz"], frame["rgba"])
        if self.state.get("source") == "svo":
            if not self.seek.isSliderDown():
                self.seek.setValue(frame["position"])
            self.position.setText(f"{frame['position'] + 1} / {frame['frames']}")
        else:
            self.position.setText(f"Live · {frame['fps']:.1f} FPS · {len(frame['xyz']):,} points")
        if self.state.get("recording"):
            self.stats.setText(f"● REC  {frame['record_seconds']:.1f}s · {frame['record_frames']} frames")
        if self.pending_capture and self.state.get("source") == "live":
            action, self.pending_capture = self.pending_capture, None
            self.execute_capture(action)

    def update_controls(self):
        live = self.state.get("source") == "live"
        recording = self.state.get("recording", False)
        svo = self.state.get("source") == "svo"
        ready = self.worker.isRunning() and not self.busy
        self.shutter.setEnabled(ready and not recording)
        self.shutter.setText("Take photo + SVO" if live else "Take new photo")
        self.shutter.setToolTip("Automatically returns to the live camera when reviewing saved media. Saves full capture resolution.")
        self.record_btn.setEnabled(ready)
        self.record_btn.setText("■  Stop video recording" if recording else
                                "●  Start video recording" if live else "●  Record new video")
        self.return_live_btn.setEnabled(ready and not live and not recording)
        self.connect_btn.setEnabled(not self.busy and not recording)
        self.disconnect_btn.setEnabled(bool(self.state.get("source")) and not self.busy)
        self.native_btn.setEnabled(not self.busy and not recording)
        self.play_btn.setEnabled(svo and not self.busy)
        self.play_btn.setText("Play" if self.state.get("paused") else "Pause")
        self.seek.setEnabled(svo and not self.busy)
        for widget in (self.resolution, self.fps, self.depth_mode):
            widget.setEnabled(not self.busy and not recording)
        for widget in (self.profile, self.wb_auto, self.exposure_auto, self.center_metering, self.apply_tuning_btn):
            widget.setEnabled(ready and not recording)
        self.review_btn.setEnabled(bool(self.selected) and not self.busy and not recording)
        self.folder_btn.setEnabled(bool(self.selected))
        exporting = self.exporter is not None and self.exporter.isRunning()
        self.export_btn.setEnabled(bool(self.selected and self.selected["kind"] == "video") and not exporting and not recording)

    def refresh_library(self, *_):
        previous = self.selected.get("id") if self.selected else None
        self.library.blockSignals(True)
        self.library.clear()
        chosen = None
        for item in list_media(self.data_root):
            if self.filter.currentIndex() == 1 and item["kind"] != "photo":
                continue
            if self.filter.currentIndex() == 2 and item["kind"] != "video":
                continue
            prefix = "PHOTO" if item["kind"] == "photo" else "VIDEO"
            detail = "PNG + depth + PLY + SVO" if item["kind"] == "photo" else f"{item.get('frames', 0)} frames · SVO"
            row = QListWidgetItem(f"{prefix}   {item['id'][:15]}\n{detail}")
            row.setIcon(QIcon(str(item["folder"] / item.get("thumbnail", "left.png"))))
            row.setData(Qt.ItemDataRole.UserRole, item)
            self.library.addItem(row)
            if item["id"] == previous:
                chosen = row
        self.library.blockSignals(False)
        if chosen:
            self.library.blockSignals(True)
            self.library.setCurrentItem(chosen)
            self.library.blockSignals(False)
            self.selected = chosen.data(Qt.ItemDataRole.UserRole)
        else:
            self.selected = None
        self.update_controls()

    def select_media(self, current, previous):
        if current is None:
            self.selected = None
            self.update_controls()
            return
        self.selected = current.data(Qt.ItemDataRole.UserRole)
        media = self.selected
        self.meta_label.setText(f"{media['kind'].title()} · {media.get('created', '')[:19]}\n"
                                f"{media.get('resolution', ['?', '?'])[0]}×{media.get('resolution', ['?', '?'])[1]} · {media.get('compression', '')}\n"
                                "Click Review selected SVO for color, depth and 3D.")
        if media["kind"] == "photo" and not self.state.get("recording") and not self.busy:
            # Selecting a still explicitly leaves live mode, so displays cannot mix sources.
            self.pending_still = media
            self.set_busy("Loading saved photo…")
            self.worker.submit("disconnect")
        self.update_controls()

    def review_svo(self):
        if self.selected:
            self.load_svo(self.selected["folder"] / self.selected["svo"])

    def open_svo_file(self):
        if self.state.get("recording") or self.busy:
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Open SVO", str(self.data_root), "ZED recordings (*.svo *.svo2)")
        if filename:
            self.load_svo(Path(filename))

    def load_svo(self, path):
        if self.state.get("recording") or self.busy:
            return
        self.clear_views()
        self.set_busy("Opening SVO and computing depth…")
        self.worker.submit("open", path=path, depth_mode=self.depth_mode.currentText(),
                           profile=self.profile.currentData())

    def set_lidar(self, value):
        self.cloud.lidar = value
        if self.cloud.xyz is not None:
            self.cloud.set_cloud(self.cloud.xyz, self.cloud.rgba)

    @staticmethod
    def open_folder(folder):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_selected_folder(self):
        if self.selected:
            self.open_folder(self.selected["folder"])

    def open_native(self):
        path = None
        if self.state.get("source") == "svo":
            path = self.state["path"]
        elif not self.state.get("source") and self.selected:
            path = str(self.selected["folder"] / self.selected["svo"])
        self.pending_native = [path] if path else []
        self.set_busy("Releasing this app's camera and opening ZED Depth Viewer…")
        self.worker.submit("disconnect")

    def launch_native(self, args):
        self.busy = False
        try:
            executable = sdk_root() / "tools" / ("ZED Depth Viewer.exe" if os.name == "nt" else "ZED_Depth_Viewer")
            if not executable.is_file():
                raise RuntimeError(f"Depth Viewer was not found at {executable}")
            # SDK 5.3 Depth Viewer ignores a positional SVO filename. Its source
            # picker is the supported way to open an SVO in that installed tool.
            subprocess.Popen([str(executable)], cwd=str(executable.parent),
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if args:
                QApplication.clipboard().setText(str(Path(args[0]).resolve()))
                self.banner.setText("ZED Depth Viewer opened. Click its SVO source icon and paste the selected file path (copied to clipboard).")
            else:
                self.banner.setText("ZED Depth Viewer opened. Close it before clicking Connect live to return camera access.")
        except Exception as exc:
            self.banner.setText("Could not launch ZED Depth Viewer: " + str(exc))
        self.update_controls()

    def export_mp4(self):
        if not self.selected or self.selected["kind"] != "video":
            return
        folder = self.selected["folder"]
        output = folder / "left_video.mp4"
        if output.exists():
            self.banner.setText(f"MP4 already exists: {output}")
            self.open_folder(folder)
            return
        self.exporter = ExportWorker(folder / self.selected["svo"], output)
        self.exporter.progress.connect(self.banner.setText)
        self.exporter.completed.connect(lambda path: self.banner.setText(f"MP4 saved: {path}"))
        self.exporter.failed.connect(lambda error: self.banner.setText("Export error: " + error))
        self.exporter.finished.connect(self.update_controls)
        self.exporter.start()
        self.banner.setText("Exporting left-camera video to MP4…")
        self.update_controls()

    def closeEvent(self, event):
        self.timer.stop()
        self.banner.setText("Finalizing recording and closing the camera…")
        self.worker.submit("quit")
        if self.exporter and self.exporter.isRunning():
            self.exporter.requestInterruption()
        # Never terminate a thread while an SVO encoder is finalizing its file.
        if not self.worker.wait(100):
            event.ignore()
            QTimer.singleShot(300, self.close)
            return
        if self.exporter and not self.exporter.wait(100):
            event.ignore()
            QTimer.singleShot(300, self.close)
            return
        event.accept()
