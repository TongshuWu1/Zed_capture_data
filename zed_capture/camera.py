"""One thread owns the camera. All SDK operations stay on that thread."""
import logging
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .sdk import load_sl
from .config import (DEFAULT_RESOLUTION, DEFAULT_FPS, DEFAULT_DEPTH_MODE, RECORDING_SVO_VERSION,
                     DEFAULT_CAPTURE_PROFILE, CAPTURE_PROFILES, AUTO_SETTLE_SECONDS)
from .tuning import apply_auto_controls, read_controls
from .storage import new_capture, commit_metadata, point_arrays

log = logging.getLogger(__name__)


class CameraWorker(QThread):
    event = Signal(str, object)

    def __init__(self, data_root: Path):
        super().__init__()
        self.data_root = data_root
        self.commands = queue.Queue()
        self.frame_lock = threading.Lock()
        self.latest = None
        self.camera = None
        self.source = None
        self.paused = False
        self.recording = None
        self.running = True
        self.last_publish = 0.0
        self.last_good = time.monotonic()
        self.record_count = 0
        self.seek_pending = False
        self.info = {}
        self.svo_position_offset = None
        self.requested_svo_frame = 0

    def submit(self, command, **args):
        self.commands.put((command, args))

    def take_latest(self):
        with self.frame_lock:
            frame, self.latest = self.latest, None
        return frame

    def check(self, status, context):
        # ZED negative codes are warnings (e.g. calibration); positive codes are errors.
        if status > self.sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"{context}: {status}")

    def run(self):
        try:
            self.sl = load_sl()
            self.runtime = self.sl.RuntimeParameters()
            self.runtime.confidence_threshold = 95
            self.runtime.texture_confidence_threshold = 100
            self.runtime.enable_fill_mode = False
            self.runtime.remove_saturated_areas = True
            self.event.emit("ready", {"sdk": self.sl.Camera.get_sdk_version()})
            while self.running:
                try:
                    command, args = self.commands.get(timeout=0.01 if not self.camera else 0)
                    self.handle(command, args)
                    # Process control commands before another grab.
                    continue
                except queue.Empty:
                    pass
                except Exception as exc:
                    log.exception("Camera command failed")
                    self.emit_state()
                    self.event.emit("error", str(exc))
                if not self.camera or (self.paused and not self.seek_pending):
                    self.msleep(10)
                    continue
                grab_start = time.monotonic()
                status = self.camera.grab(self.runtime)
                if status == self.sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                    self.paused = True
                    self.event.emit("notice", "End of SVO. Seek or press Play to restart.")
                    self.emit_state()
                    continue
                if status > self.sl.ERROR_CODE.SUCCESS:
                    if time.monotonic() - self.last_good > 4:
                        self.event.emit("error", f"Camera stopped delivering frames: {status}")
                        self.close_source()
                    self.msleep(30)
                    continue
                self.last_good = time.monotonic()
                if self.recording:
                    rec_status = self.camera.get_recording_status()
                    self.record_count += 1
                    self.encoding_false_run = 0 if rec_status.status else self.encoding_false_run + 1
                    # On SDK 5.3 H.26x, the first status can be false even though
                    # the frame is encoded successfully on finalization. A real
                    # loss of recording or sustained failure still stops capture.
                    if not rec_status.is_recording or self.encoding_false_run >= 30:
                        self.stop_recording()
                        self.event.emit("error", "SVO encoder failed. The partial recording was finalized.")
                if time.monotonic() - self.last_publish >= 1 / 15 or self.seek_pending:
                    self.publish_frame()
                    self.seek_pending = False
                if self.source == "svo" and not self.paused:
                    self.msleep(max(0, int((self.frame_interval - (time.monotonic() - grab_start)) * 1000)))
        except Exception as exc:
            log.exception("Camera worker failed")
            self.event.emit("error", str(exc))
        finally:
            self.close_source()

    def handle(self, command, args):
        if command == "quit":
            self.running = False
        elif command == "disconnect":
            self.close_source()
        elif command == "open":
            self.open_source(**args)
        elif command == "photo":
            self.capture_photo()
        elif command == "record":
            self.start_recording()
        elif command == "stop_record":
            self.stop_recording()
        elif command == "camera_settings":
            self.require_live()
            if self.recording:
                raise RuntimeError("Stop recording before changing camera controls.")
            controls = apply_auto_controls(self.camera, self.sl, **args)
            self.settle_controls(self.camera, args.get("auto_white_balance", True) or args.get("auto_exposure", True))
            controls.update(read_controls(self.camera, self.sl))
            self.info["camera_controls"] = controls
            self.emit_state()
            self.event.emit("notice", "Camera tuning applied. Auto controls have had a one-second settling interval.")
        elif command == "pause" and self.source == "svo":
            self.paused = not self.paused
            if (not self.paused and self.svo_position_offset is not None
                    and self.get_svo_frame_position() >= self.frame_count - 1):
                self.camera.set_svo_position(0)
            self.emit_state()
        elif command == "seek" and self.source == "svo":
            self.requested_svo_frame = max(0, min(args["frame"], self.frame_count - 1))
            self.camera.set_svo_position(self.requested_svo_frame)
            self.seek_pending = True
        elif command == "confidence":
            self.runtime.confidence_threshold = args["value"]
            if self.source == "svo" and self.paused:
                frame = self.get_svo_frame_position() if self.svo_position_offset is not None else self.requested_svo_frame
                self.camera.set_svo_position(frame)
                self.seek_pending = True

    def emit_state(self):
        self.event.emit("state", {"source": self.source, "paused": self.paused,
                                  "recording": bool(self.recording), **self.info})

    def open_source(self, path=None, resolution=DEFAULT_RESOLUTION, fps=DEFAULT_FPS,
                    depth_mode=DEFAULT_DEPTH_MODE, profile=DEFAULT_CAPTURE_PROFILE,
                    auto_white_balance=True, auto_exposure=True, center_metering=True):
        settings = CAPTURE_PROFILES[profile]
        self.close_source(emit=False)
        self.event.emit("notice", "Opening ZED / initializing depth model…")
        sl = self.sl
        init = sl.InitParameters()
        init.coordinate_units = sl.UNIT.METER
        init.coordinate_system = sl.COORDINATE_SYSTEM.RIGHT_HANDED_Y_UP
        init.depth_mode = getattr(sl.DEPTH_MODE, depth_mode)
        init.depth_minimum_distance = settings["depth_min"]
        init.depth_maximum_distance = settings["depth_max"]
        if path:
            init.set_from_svo_file(str(path))
            init.svo_real_time_mode = False
        else:
            init.camera_resolution = getattr(sl.RESOLUTION, resolution)
            init.camera_fps = fps
        camera = sl.Camera()
        try:
            status = camera.open(init)
            if not path and status == getattr(sl.ERROR_CODE, "CAMERA_STREAM_FAILED_TO_START", None):
                raise RuntimeError("Open ZED: CAMERA STREAM FAILED TO START. "
                    "Another capture window, ZED Depth Viewer, Explorer, or Studio may already be using the camera. "
                    "Close it and click Back to live. If no app is using the camera, check its USB 3 connection.")
            self.check(status, "Open ZED")
            controls = None
            if not path:
                self.event.emit("notice", "Applying auto white balance / exposure and allowing them to settle…")
                controls = apply_auto_controls(camera, sl, auto_white_balance, auto_exposure, center_metering)
                self.settle_controls(camera, auto_white_balance or auto_exposure)
                controls.update(read_controls(camera, sl))
        except Exception:
            camera.close()
            raise
        self.camera = camera
        self.source = "svo" if path else "live"
        self.paused = bool(path)  # The first frame is shown without advancing a photo's SVO.
        self.seek_pending = bool(path)
        self.frame_count = camera.get_svo_number_of_frames() if path else 0
        self.svo_position_offset = None
        self.requested_svo_frame = 0
        if path and self.frame_count:
            camera.set_svo_position(0)
        self.frame_interval = 1 / max(1, camera.get_camera_information().camera_configuration.fps)
        config = camera.get_camera_information()
        size = config.camera_configuration.resolution
        self.full_resolution = size
        self.preview_size = sl.Resolution(min(960, size.width),
                                         round(size.height * min(960, size.width) / size.width))
        self.cloud_size = sl.Resolution(min(640, size.width),
                                       round(size.height * min(640, size.width) / size.width))
        self.left, self.depth_view, self.cloud = sl.Mat(), sl.Mat(), sl.Mat()
        self.info = {"model": str(config.camera_model), "serial": config.serial_number,
                     "resolution": [size.width, size.height],
                     "fps": config.camera_configuration.fps,
                     "depth_mode": depth_mode, "sdk": sl.Camera.get_sdk_version(),
                     "frames": self.frame_count, "path": str(path) if path else None,
                     "capture_profile": profile,
                     "depth_minimum_distance": camera.get_init_parameters().depth_minimum_distance,
                     "depth_maximum_distance": camera.get_init_parameters().depth_maximum_distance}
        if controls is not None:
            self.info["camera_controls"] = controls
        self.last_good = time.monotonic()
        self.last_publish = 0
        self.emit_state()

    def settle_controls(self, camera, enabled=True):
        if enabled:
            deadline = time.monotonic() + AUTO_SETTLE_SECONDS
            while time.monotonic() < deadline:
                self.check(camera.grab(self.runtime), "Allow automatic camera controls to settle")

    def publish_frame(self):
        sl = self.sl
        self.check(self.camera.retrieve_image(self.left, sl.VIEW.LEFT, sl.MEM.CPU, self.preview_size), "Read color")
        self.check(self.camera.retrieve_image(self.depth_view, sl.VIEW.DEPTH, sl.MEM.CPU, self.preview_size), "Read depth view")
        self.check(self.camera.retrieve_measure(self.cloud, sl.MEASURE.XYZRGBA, sl.MEM.CPU, self.cloud_size), "Read point cloud")
        xyz, rgba = point_arrays(self.cloud.get_data())
        now = time.monotonic()
        frame = {"left": self.left.get_data().copy(), "depth": self.depth_view.get_data().copy(),
                 "xyz": xyz, "rgba": rgba,
                 "position": self.get_svo_frame_position() if self.source == "svo" else 0,
                 "frames": self.frame_count, "record_frames": self.record_count,
                 "record_seconds": now - self.record_start if self.recording else 0,
                 "fps": self.camera.get_current_fps()}
        with self.frame_lock:
            self.latest = frame
        self.last_publish = now

    def get_svo_frame_position(self):
        raw_position = self.camera.get_svo_position()
        if self.svo_position_offset is None:
            # SDK 5.3 reports the next-frame cursor for legacy SVO, but the
            # current-frame index for SVO2. Detect from the first requested read.
            offset = raw_position - self.requested_svo_frame
            if offset not in (0, 1):
                raise RuntimeError(f"Unexpected SVO cursor offset: {offset}")
            self.svo_position_offset = offset
        return max(0, min(raw_position - self.svo_position_offset, self.frame_count - 1))

    def require_live(self):
        if self.source != "live" or not self.camera:
            raise RuntimeError("Connect the live ZED camera first.")

    def capture_photo(self):
        self.require_live()
        if self.recording:
            raise RuntimeError("Stop video recording before capturing a photo with its own SVO.")
        sl = self.sl
        folder, meta = new_capture(self.data_root, "photo")
        svo = folder / "frame.svo"
        # LOSSLESS avoids inter-frame encoder buffering and preserves a one-frame SVO.
        self.check(self.camera.enable_recording(sl.RecordingParameters(str(svo), sl.SVO_COMPRESSION_MODE.LOSSLESS)), "Start photo SVO")
        try:
            self.check(self.camera.grab(self.runtime), "Capture photo frame")
            if not self.camera.get_recording_status().status:
                raise RuntimeError("SDK did not record the photo frame.")
            timestamp = self.camera.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_nanoseconds()
            captured_controls = {**self.info.get("camera_controls", {}), **read_controls(self.camera, sl)}
            for name, view in (("left.png", sl.VIEW.LEFT), ("right.png", sl.VIEW.RIGHT),
                               ("raw_left.png", sl.VIEW.LEFT_UNRECTIFIED),
                               ("raw_right.png", sl.VIEW.RIGHT_UNRECTIFIED),
                               ("depth_preview.png", sl.VIEW.DEPTH)):
                image = sl.Mat()
                self.check(self.camera.retrieve_image(image, view), f"Retrieve {name}")
                self.check(image.write(str(folder / name)), f"Save {name}")
            depth = sl.Mat()
            self.check(self.camera.retrieve_measure(depth, sl.MEASURE.DEPTH), "Retrieve metric depth")
            np.save(folder / "depth_m.npy", depth.get_data())
            cloud = sl.Mat()
            self.check(self.camera.retrieve_measure(cloud, sl.MEASURE.XYZRGBA), "Retrieve full point cloud")
            self.check(cloud.write(str(folder / "cloud.ply")), "Save PLY")
        finally:
            self.camera.disable_recording()
        actual_frames = self.finalized_frame_count(svo)
        if actual_frames != 1:
            raise RuntimeError(f"Photo SVO validation failed: expected 1 frame, found {actual_frames}. Files retained at {folder}")
        meta.update(self.info)
        meta.update({"svo": "frame.svo", "svo_version": RECORDING_SVO_VERSION,
                     "camera_controls": captured_controls,
                     "thumbnail": "left.png", "timestamp_ns": timestamp,
                     "frames": 1, "compression": "LOSSLESS", "depth_file": "depth_m.npy",
                     "raw_images": ["raw_left.png", "raw_right.png"],
                     "invalid_depth": "NaN / +/-Inf, excluded from the point cloud viewer"})
        commit_metadata(folder, meta)
        self.event.emit("saved", folder)

    def start_recording(self):
        self.require_live()
        if self.recording:
            return
        folder, meta = new_capture(self.data_root, "video")
        sl = self.sl
        codec = sl.SVO_COMPRESSION_MODE.LOSSLESS
        self.check(self.camera.enable_recording(
            sl.RecordingParameters(str(folder / "recording.svo"), codec)), "Start lossless SVO")
        meta["compression"] = codec.name
        meta.update(self.info)
        meta["camera_controls_start"] = {**self.info.get("camera_controls", {}), **read_controls(self.camera, sl)}
        meta.update({"svo": "recording.svo", "svo_version": RECORDING_SVO_VERSION,
                     "thumbnail": "thumbnail.png"})
        # Write the thumbnail before any further grab, matching the session start.
        image = sl.Mat()
        self.camera.retrieve_image(image, sl.VIEW.LEFT)
        image.write(str(folder / "thumbnail.png"))
        self.recording = (folder, meta)
        self.record_count = 0
        self.encoding_false_run = 0
        self.record_start = time.monotonic()
        self.emit_state()

    def stop_recording(self):
        if not self.recording:
            return
        folder, meta = self.recording
        meta["camera_controls_end"] = read_controls(self.camera, self.sl)
        self.camera.disable_recording()
        self.recording = None
        actual_frames = self.finalized_frame_count(folder / "recording.svo")
        meta.update({"frames": actual_frames, "grabbed_frames": self.record_count,
                     "duration_seconds": time.monotonic() - self.record_start})
        if not actual_frames:
            raise RuntimeError(f"Recording contains no frames. Incomplete files retained at {folder}")
        commit_metadata(folder, meta)
        self.event.emit("saved", folder)
        self.emit_state()

    def finalized_frame_count(self, path):
        reader = self.sl.Camera()
        init = self.sl.InitParameters()
        init.set_from_svo_file(str(path))
        init.depth_mode = self.sl.DEPTH_MODE.NONE
        try:
            self.check(reader.open(init), "Validate finalized SVO")
            return reader.get_svo_number_of_frames()
        finally:
            reader.close()

    def close_source(self, emit=True):
        try:
            self.stop_recording()
        finally:
            if self.camera:
                self.camera.close()
            self.camera = None
            self.source = None
            self.info = {}
            self.paused = False
            with self.frame_lock:
                self.latest = None
            if emit:
                self.emit_state()


class ExportWorker(QThread):
    progress = Signal(str)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, source: Path, output: Path):
        super().__init__()
        self.source, self.output = source, output

    def run(self):
        camera, writer = None, None
        temp = self.output.with_name(self.output.stem + ".partial.mp4")
        try:
            sl = load_sl()
            camera = sl.Camera()
            init = sl.InitParameters()
            init.set_from_svo_file(str(self.source))
            init.svo_real_time_mode = False
            init.depth_mode = sl.DEPTH_MODE.NONE
            status = camera.open(init)
            if status > sl.ERROR_CODE.SUCCESS:
                raise RuntimeError(f"Open export SVO: {status}")
            config = camera.get_camera_information().camera_configuration
            size = config.resolution
            writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*"mp4v"),
                                     config.fps, (size.width, size.height))
            if not writer.isOpened():
                raise RuntimeError("MP4 encoder is unavailable on this PC.")
            image, count = sl.Mat(), 0
            total = camera.get_svo_number_of_frames()
            while not self.isInterruptionRequested():
                status = camera.grab()
                if status == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                    break
                if status > sl.ERROR_CODE.SUCCESS:
                    raise RuntimeError(f"Read export frame: {status}")
                camera.retrieve_image(image, sl.VIEW.LEFT)
                writer.write(np.ascontiguousarray(image.get_data()[:, :, :3]))
                count += 1
                if count % 30 == 0:
                    self.progress.emit(f"Exporting MP4 · {count}/{total} frames")
            if self.isInterruptionRequested():
                raise RuntimeError("MP4 export cancelled. Original SVO is safe.")
            if not count:
                raise RuntimeError("This SVO contains no readable frames.")
            if count != total:
                raise RuntimeError(f"The SDK returned {count} of {total} advertised SVO frames. "
                                   f"Incomplete export retained at {temp}; the original SVO is unchanged.")
            writer.release()
            writer = None
            temp.replace(self.output)
            self.completed.emit(str(self.output))
        except Exception as exc:
            log.exception("MP4 export failed")
            self.failed.emit(str(exc))
        finally:
            if writer:
                writer.release()
            if camera:
                camera.close()
