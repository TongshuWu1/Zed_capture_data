"""Portable media folders; metadata is committed only after files are finalized."""
import json
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PROJECT_ROOT / "data"


def new_capture(root: Path, kind: str) -> tuple[Path, dict]:
    now = datetime.now().astimezone()
    capture_id = now.strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid.uuid4().hex[:8]
    folder = root / ("photos" if kind == "photo" else "recordings") / capture_id
    folder.mkdir(parents=True, exist_ok=False)
    return folder, {"schema": 1, "kind": kind, "created": now.isoformat(),
                    "id": folder.name, "units": "meters",
                    "coordinate_system": "RIGHT_HANDED_Y_UP"}


def commit_metadata(folder: Path, metadata: dict):
    temp = folder / "metadata.json.tmp"
    temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    temp.replace(folder / "metadata.json")


def list_media(root: Path) -> list[dict]:
    entries = []
    for category in ("photos", "recordings"):
        for path in (root / category).glob("*/metadata.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["folder"] = path.parent
                entries.append(data)
            except (OSError, ValueError):
                continue
    return sorted(entries, key=lambda item: item.get("created", ""), reverse=True)


def point_arrays(cloud):
    """Decode SDK XYZRGBA floats: the fourth float contains four packed color bytes."""
    import numpy as np
    flat = np.ascontiguousarray(cloud, dtype=np.float32).reshape(-1, 4)
    valid = np.isfinite(flat[:, :3]).all(axis=1)
    xyz = flat[valid, :3].copy()
    colors = flat[:, 3].copy().view(np.uint8).reshape(-1, 4)[valid].copy()
    colors[:, 3] = 255
    return xyz, colors.astype(np.float32) / 255.0
