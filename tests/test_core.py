import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from zed_capture.storage import new_capture, commit_metadata, list_media, point_arrays
from zed_capture.camera import CameraWorker


class StorageTests(unittest.TestCase):
    def test_only_completed_captures_appear_in_library(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            incomplete, _ = new_capture(root, "photo")
            photo, metadata = new_capture(root, "photo")
            video, video_metadata = new_capture(root, "video")
            commit_metadata(photo, metadata)
            commit_metadata(video, video_metadata)
            (incomplete / "metadata.json").write_text("invalid JSON")
            result = list_media(root)
            self.assertEqual({x["kind"] for x in result}, {"video", "photo"})
            self.assertEqual(next(x["folder"] for x in result if x["kind"] == "photo"), photo)
            self.assertEqual([x["created"] for x in result], sorted([metadata["created"], video_metadata["created"]], reverse=True))
            self.assertFalse((photo / "metadata.json.tmp").exists())

    def test_point_cloud_filters_invalid_xyz_and_preserves_rgba_bytes(self):
        rgba = np.array([[10, 20, 30, 255], [1, 2, 3, 255], [4, 5, 6, 255]], dtype=np.uint8)
        cloud = np.zeros((1, 3, 4), dtype=np.float32)
        cloud[0, :, :3] = [[1, 2, -3], [np.nan, 0, 0], [0, np.inf, 0]]
        cloud[0, :, 3] = rgba.copy().view(np.float32).ravel()
        xyz, colors = point_arrays(cloud)
        np.testing.assert_array_equal(xyz, [[1, 2, -3]])
        np.testing.assert_allclose(colors, [[10/255, 20/255, 30/255, 1]])

    def test_camera_is_released_when_recording_finalize_fails(self):
        worker = CameraWorker(Path("unused"))
        camera = Mock()
        worker.camera = camera
        worker.source = "live"
        worker.stop_recording = Mock(side_effect=OSError("disk full"))
        with self.assertRaisesRegex(OSError, "disk full"):
            worker.close_source()
        camera.close.assert_called_once()
        self.assertIsNone(worker.camera)

    def test_only_latest_frame_is_kept_for_ui(self):
        worker = CameraWorker(Path("unused"))
        worker.latest = {"position": 42}
        self.assertEqual(worker.take_latest(), {"position": 42})
        self.assertIsNone(worker.take_latest())

    def test_legacy_svo_cursor_is_normalized_to_displayed_frame(self):
        worker = CameraWorker(Path("unused"))
        worker.camera = Mock()
        worker.frame_count = 19
        worker.camera.get_svo_position.return_value = 1
        self.assertEqual(worker.get_svo_frame_position(), 0)
        worker.camera.get_svo_position.return_value = 19
        self.assertEqual(worker.get_svo_frame_position(), 18)

    def test_svo2_current_frame_index_is_preserved(self):
        worker = CameraWorker(Path("unused"))
        worker.camera = Mock()
        worker.frame_count = 19
        worker.camera.get_svo_position.return_value = 0
        self.assertEqual(worker.get_svo_frame_position(), 0)
        worker.camera.get_svo_position.return_value = 18
        self.assertEqual(worker.get_svo_frame_position(), 18)


if __name__ == "__main__":
    unittest.main()
