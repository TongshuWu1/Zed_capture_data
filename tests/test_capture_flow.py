"""Source-switch regressions; no camera, SDK, network or desktop interaction."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
from zed_capture.ui import MainWindow


class FakeWorker(QObject):
    event = Signal(str, object)

    def __init__(self, root):
        super().__init__()
        self.commands = []
        self.latest = None

    def start(self):
        pass

    def isRunning(self):
        return True

    def submit(self, command, **args):
        self.commands.append((command, args))

    def take_latest(self):
        frame, self.latest = self.latest, None
        return frame

    def wait(self, timeout):
        return True


class FakeCloud(QWidget):
    def __init__(self):
        super().__init__()
        self.grid = Mock()
        self.xyz = self.rgba = None

    def home(self):
        pass

    def set_profile(self, profile):
        self.capture_profile = profile

    def clear_cloud(self):
        self.xyz = self.rgba = None

    def set_cloud(self, xyz, rgba):
        self.xyz, self.rgba = xyz, rgba


class CaptureFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch("zed_capture.ui.CameraWorker", FakeWorker),
                        patch("zed_capture.ui.CloudView", FakeCloud)]
        for item in self.patches:
            item.start()
        self.window = MainWindow(Path(self.temp.name), autoconnect=False)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def source_state(self, source, recording=False):
        self.window.on_event("state", {"source": source, "paused": source == "svo",
            "recording": recording, "model": "ZED 2i", "resolution": [2208, 1242],
            "depth_mode": "NEURAL_PLUS", "frames": 10, "path": "recording.svo2"})

    def fresh_frame(self):
        self.window.worker.latest = {"left": np.zeros((2, 2, 4), dtype=np.uint8),
            "depth": np.zeros((2, 2, 4), dtype=np.uint8), "xyz": np.zeros((1, 3)),
            "rgba": np.ones((1, 4)), "position": 0, "frames": 0, "fps": 15,
            "record_frames": 0, "record_seconds": 0}
        self.window.poll_frame()

    def test_photo_from_review_waits_for_fresh_live_frame(self):
        self.source_state("svo")
        self.window.shutter.click()
        self.assertEqual(self.window.pending_capture, "photo")
        self.assertEqual(self.window.worker.commands, [("open", {
            "resolution": "HD2K", "fps": 15, "depth_mode": "NEURAL_PLUS", "profile": "close",
            "auto_white_balance": True, "auto_exposure": True, "center_metering": True})])
        self.source_state("live")
        self.assertFalse(self.window.shutter.isEnabled())
        self.assertEqual(len(self.window.worker.commands), 1)
        self.fresh_frame()
        self.assertEqual(self.window.worker.commands[-1], ("photo", {}))
        self.assertIsNone(self.window.pending_capture)

    def test_record_from_review_reconnects_without_extra_connect_click(self):
        self.source_state("svo")
        self.window.record_btn.click()
        self.source_state("live")
        self.fresh_frame()
        self.assertEqual([c for c, _ in self.window.worker.commands], ["open", "record"])

    def test_failed_reconnect_cancels_pending_capture(self):
        self.source_state("svo")
        self.window.shutter.click()
        self.window.on_event("error", "Camera not available")
        self.assertIsNone(self.window.pending_capture)
        self.source_state("live")
        self.fresh_frame()
        self.assertEqual([c for c, _ in self.window.worker.commands], ["open"])

    def test_back_to_live_does_not_start_recording(self):
        self.source_state("svo")
        self.window.return_live_btn.click()
        self.source_state("live")
        self.fresh_frame()
        self.assertEqual([c for c, _ in self.window.worker.commands], ["open"])

    def test_photo_cannot_interrupt_active_video(self):
        self.source_state("live", recording=True)
        self.window.shutter.click()
        self.assertEqual(self.window.worker.commands, [])
        self.window.record_btn.click()
        self.assertEqual(self.window.worker.commands, [("stop_record", {})])

    def test_tuning_is_disabled_while_recording(self):
        self.source_state("live", recording=True)
        self.assertFalse(self.window.apply_tuning_btn.isEnabled())
        self.window.apply_tuning_btn.click()
        self.assertEqual(self.window.worker.commands, [])

    def test_apply_image_tuning_does_not_reopen_same_profile(self):
        self.source_state("live")
        self.window.state["capture_profile"] = "close"
        self.window.apply_tuning_btn.click()
        self.assertEqual(self.window.worker.commands, [("camera_settings", {
            "auto_white_balance": True, "auto_exposure": True, "center_metering": True})])
