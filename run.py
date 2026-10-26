"""Portable entry point: run with stock Python 3.11 from PyCharm or a terminal."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Set up the local Python environment and launch ZED Capture.")
    parser.add_argument("--setup-only", action="store_true", help="Install/verify dependencies without launching the UI")
    parser.add_argument("--no-autoconnect", action="store_true", help="Launch without opening the camera")
    parser.add_argument("--data-dir", type=Path, help="Override the default project/data folder")
    args = parser.parse_args()
    try:
        from setup_env import environment_ready, environment_python, main as setup
        if not environment_ready():
            print("Preparing this project's .venv (first run or changed SDK/dependencies)…", flush=True)
            setup()
        if args.setup_only:
            print("ZED Capture is ready.")
            return 0
        command = [str(environment_python()), str(ROOT / "main.py")]
        if args.no_autoconnect:
            command.append("--no-autoconnect")
        if args.data_dir:
            # Resolve relative paths against the caller's directory before changing cwd.
            command.extend(["--data-dir", str(args.data_dir.resolve())])
        return subprocess.call(command, cwd=ROOT)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Cannot start ZED Capture: {exc}\nInstall the ZED SDK and 64-bit Python 3.11, "
              "then run python run.py again. See README.md.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
