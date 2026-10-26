"""Create the local virtualenv and install the Python API matching your ZED SDK."""
import os
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def environment_python():
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def environment_fingerprint():
    from zed_capture.sdk import sdk_root
    sdk = sdk_root()
    version_file = sdk / "zed-config-version.cmake"
    sdk_version = version_file.read_bytes() if version_file.exists() else (sdk / "get_python_api.py").read_bytes()
    data = (ROOT / "requirements.txt").read_bytes() + sdk_version
    return hashlib.sha256(data + f"{ROOT}:{platform.system()}:{platform.machine()}".encode()).hexdigest()


def environment_ready():
    marker = ROOT / ".venv" / ".zed-capture-ready.json"
    try:
        return (environment_python().is_file() and
                json.loads(marker.read_text())["fingerprint"] == environment_fingerprint())
    except (OSError, ValueError, KeyError):
        return False


def main():
    if sys.version_info[:2] != (3, 11) or platform.architecture()[0] != "64bit":
        raise RuntimeError("Use 64-bit Python 3.11 for this project's tested dependency set.")
    from zed_capture.sdk import sdk_root
    sdk = sdk_root()  # Fail before downloading packages when the native SDK is missing.
    installer = sdk / "get_python_api.py"
    if not installer.is_file():
        raise RuntimeError(f"ZED Python installer is missing: {installer}")
    target = environment_python()
    if not target.exists():
        subprocess.check_call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    subprocess.check_call([str(target), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    env = os.environ.copy()
    env["ZED_SDK_ROOT_DIR"] = str(sdk)
    env["PIP_CONSTRAINT"] = str(ROOT / "requirements.txt")
    with tempfile.TemporaryDirectory(prefix="zed_python_") as cache:
        subprocess.check_call([str(target), str(installer), "--path", cache], env=env)
    subprocess.check_call([str(target), "-c", "from zed_capture.sdk import load_sl; sl=load_sl(); "
                           "import PySide6, cv2, numpy, pyqtgraph; "
                           "print('Ready. ZED SDK:',sl.Camera.get_sdk_version())"], cwd=ROOT)
    subprocess.check_call([str(target), "-m", "pip", "check"])
    (ROOT / ".venv" / ".zed-capture-ready.json").write_text(
        json.dumps({"fingerprint": environment_fingerprint()}, indent=2), encoding="utf-8")
    print(f"\nPyCharm interpreter: {target}\nRun run.py to launch ZED Capture.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
