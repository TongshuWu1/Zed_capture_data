"""Quality-first capture defaults (ZED 2 / 2i / Mini)."""
DEFAULT_RESOLUTION = "HD2K"
DEFAULT_FPS = 15
DEFAULT_DEPTH_MODE = "NEURAL_PLUS"
DEFAULT_CAPTURE_PROFILE = "close"
AUTO_SETTLE_SECONDS = 1.0
CAPTURE_PROFILES = {
    "close": {"label": "Close-up (30–100 cm)", "depth_min": 0.2, "depth_max": 2.0,
              "view_center": 0.65, "view_distance": 1.0},
    "general": {"label": "General / room", "depth_min": 0.2, "depth_max": 20.0,
                "view_center": 3.0, "view_distance": 5.0},
}
# SDK 5.3.1 SVO2 LOSSLESS altered the last four HD2K rows in pixel-equality
# checks. Legacy lossless SVO preserved the entire raw stereo frame.
RECORDING_SVO_VERSION = 1
