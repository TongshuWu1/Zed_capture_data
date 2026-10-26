"""Opt-in real camera check. Run with --data-dir PATH; writes real photo/video files."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from zed_capture.camera import CameraWorker, ExportWorker
from zed_capture.sdk import load_sl
from zed_capture.storage import list_media


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.data_dir.resolve() / f"hardware_check_{time.time_ns()}"
    worker = CameraWorker(root)
    worker.sl = load_sl()
    worker.runtime = worker.sl.RuntimeParameters()
    report = {"sdk": worker.sl.Camera.get_sdk_version(), "checks": []}
    try:
        worker.open_source()
        report["camera"] = dict(worker.info)
        for _ in range(5):
            worker.check(worker.camera.grab(worker.runtime), "Warmup")
        worker.publish_frame()
        assert len(worker.take_latest()["xyz"]) > 0, "No finite live 3D points; aim at a textured scene."
        report["checks"].append("live_color_depth_cloud")
        worker.capture_photo()
        worker.start_recording()
        end = time.monotonic() + 1.2
        while time.monotonic() < end:
            worker.check(worker.camera.grab(worker.runtime), "Video grab")
            assert worker.camera.get_recording_status().is_recording
            worker.record_count += 1
        worker.stop_recording()
    finally:
        worker.close_source()
    for media in list_media(root):
        folder = media["folder"]
        worker.open_source(path=folder / media["svo"])
        try:
            count = worker.frame_count
            assert count == media["frames"] and count > 0
            worker.check(worker.camera.grab(worker.runtime), "SVO replay")
            worker.publish_frame()
            assert len(worker.take_latest()["xyz"]) > 0, "No replay 3D points."
            if media["kind"] == "photo":
                assert count == 1
                image = worker.sl.Mat()
                for name, view in (("raw_left.png", worker.sl.VIEW.LEFT_UNRECTIFIED),
                                   ("raw_right.png", worker.sl.VIEW.RIGHT_UNRECTIFIED)):
                    worker.check(worker.camera.retrieve_image(image, view), "Read raw stereo")
                    original = cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
                    np.testing.assert_array_equal(original[:, :, :3], image.get_data()[:, :, :3])
                depth = np.load(folder / "depth_m.npy")
                assert depth.dtype == np.float32 and np.isfinite(depth).any()
                report["checks"].extend(["one_frame_photo_svo", "raw_stereo_pixel_equality", "metric_depth_saved", "photo_3d_replay"])
            else:
                worker.camera.set_svo_position(count - 1)
                worker.check(worker.camera.grab(worker.runtime), "Seek last frame")
                assert worker.get_svo_frame_position() == count - 1
                report["video_frames"] = count
                report["checks"].extend(["video_svo_replay", "seek_last_frame"])
        finally:
            worker.close_source()
        if media["kind"] == "video":
            output = folder / "left_video.mp4"
            failures = []
            exporter = ExportWorker(folder / media["svo"], output)
            exporter.failed.connect(failures.append)
            exporter.run()
            assert not failures, failures
            decoder = cv2.VideoCapture(str(output))
            decoded = 0
            try:
                while True:
                    ok, image = decoder.read()
                    if not ok:
                        break
                    assert image.shape[:2] == tuple(reversed(media["resolution"]))
                    decoded += 1
            finally:
                decoder.release()
            assert decoded == media["frames"], (decoded, media["frames"])
            report["checks"].append("mp4_all_frames_decoded")
    report["passed"] = True
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("Hardware check passed. Files:", root)


if __name__ == "__main__":
    main()
