"""Application entry point inside .venv. Use run.py for automatic first-run setup."""
import argparse
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")


def main():
    parser = argparse.ArgumentParser(description="ZED camera capture and review")
    parser.add_argument("--data-dir", type=Path, help="Media directory; defaults to project/data")
    parser.add_argument("--no-autoconnect", action="store_true", help="Launch without opening the camera")
    args = parser.parse_args()
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QSurfaceFormat
        from zed_capture.storage import DEFAULT_DATA
        from zed_capture.ui import MainWindow
        from zed_capture.instance import SingleInstance
    except ImportError as exc:
        print(f"Missing dependency: {exc}\nRun run.py with Python 3.11 to prepare this project's environment.")
        return 1
    root = (args.data_dir or DEFAULT_DATA).resolve()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(root / "logs" / "app.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(24)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ZED Capture")
    instance = SingleInstance()
    if not instance.acquire():
        print("ZED Capture is already running. Bringing the existing window forward. "
              "Close that window before restarting from PyCharm.")
        return 0
    window = MainWindow(root, autoconnect=not args.no_autoconnect)
    def activate_existing():
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()
    instance.activation_requested.connect(activate_existing)
    window.show()
    try:
        return app.exec()
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
