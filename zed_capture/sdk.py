"""Load the API matching the installed SDK, including its Windows DLLs."""
import os
from pathlib import Path

_dll_handles = []


def sdk_root() -> Path:
    candidates = [os.environ.get("ZED_SDK_ROOT_DIR", ""),
                  r"C:\Program Files (x86)\ZED SDK", r"C:\Program Files\ZED SDK",
                  "/usr/local/zed"]
    for candidate in candidates:
        if candidate and (Path(candidate) / "include").is_dir():
            return Path(candidate)
    raise RuntimeError("ZED SDK not found. Install it from stereolabs.com/developers/release.")


def load_sl():
    from .config import RECORDING_SVO_VERSION
    os.environ["ZED_SDK_SVO_VERSION"] = str(RECORDING_SVO_VERSION)
    if os.name == "nt":
        root = sdk_root()
        # Keep these handles alive: closing a handle removes its DLL search path.
        for directory in (root / "bin", root / "dependencies"):
            if directory.is_dir():
                _dll_handles.append(os.add_dll_directory(str(directory)))
    try:
        import pyzed.sl as sl
    except (ImportError, OSError) as exc:
        raise RuntimeError("Cannot load the ZED Python API. Run setup_env.py with this "
                           "project's Python interpreter. Original error: " + str(exc)) from exc
    return sl
