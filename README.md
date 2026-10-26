# ZED Capture

Quality-first stereo photography, lossless SVO video, and interactive 3D review. Run **run.py** from PyCharm or a terminal. It prepares this project's `.venv` on first launch and installs the Python API matching the local ZED SDK. No paths to the original developer's computer are needed. Camera files stay in the local `data` folder.

## Requirements on each PC

- Windows with a compatible NVIDIA GPU/driver, USB 3, and a ZED stereo camera. The tested camera is ZED 2i with an RTX 4080.
- **64-bit Python 3.11**.
- **ZED SDK 5.3.x**, installed with its native dependencies. The tested SDK is 5.3.1. Install the SDK from [StereoLabs](https://www.stereolabs.com/developers/release); the proprietary SDK, GPU driver, and hardware cannot be bundled in a GitHub Python repository.
- Internet access for first-time Python installation and any SDK neural-model download/optimization. Later launches reuse the environment and models.

Windows is tested. The bootstrap and SDK loader also support the standard Linux SDK path `/usr/local/zed`; Linux has not been hardware-tested. Other SDK versions are not covered by the validation run.

## Run from a terminal

After cloning/downloading this repository, open a terminal in its root and run:

```powershell
py -3.11 run.py
```

If `python` already points to Python 3.11, `python run.py` is equivalent. On Linux, use `python3.11 run.py` after installing the native SDK and Python venv support. The first run takes longer because it creates `.venv` and installs dependencies. Subsequent launches reuse it. `python run.py --setup-only` installs without opening the UI; `python run.py --no-autoconnect` starts without opening the camera.

To repair the Python environment after a change, run `python setup_env.py` with Python 3.11. When moving or copying the project to a different computer, create a new `.venv` using the launcher; do not copy an old virtualenv.

## Run in PyCharm

1. Open this repository folder in PyCharm. Choose a **Python 3.11** interpreter if prompted (a system interpreter or a new project virtualenv is fine).
2. Right-click **run.py → Run**. It automatically creates/prepares `.venv` and launches the UI. No manual `pyzed` wheel download is needed.
3. Once `.venv` exists, you can select `.venv\Scripts\python.exe` as the project interpreter. The shared **ZED Capture** run configuration uses this relative Windows interpreter path. On Linux, run `run.py` directly with your selected Python 3.11 interpreter.
4. The UI connects to the first available ZED camera. No separate terminal is needed for normal use.

You can also double-click **Launch ZED Capture.cmd**. Close other programs that are using the ZED before connecting. Close this app with its window's Close button to let any recording finish writing.

Only one ZED Capture UI runs per OS user. Launching it again from PyCharm or a terminal brings the existing window forward and exits the second process before it opens a camera. To restart after editing code, close the existing UI first; an already-open window continues running its previously loaded code.

## Capture and review

- **Take photo + SVO** saves rectified left/right PNGs, unrectified left/right PNGs, a colored depth preview, metric depth, a full-resolution colored PLY point cloud, and a matching lossless one-frame SVO.
- **Start video recording / Stop video recording** writes a lossless SVO recording. Stop finalizes and checks that the SVO can be opened. Lossless recording uses substantially more disk space than H.265.
- Recording uses **legacy lossless `.svo`**. On the tested SDK 5.3.1, SVO2 LOSSLESS changed the last four HD2K rows on replay; the legacy format preserved every raw stereo pixel. The full-resolution PNGs are also retained. Legacy SVO stores sensors at the image frame rate instead of SVO2's high-frequency sensor recording. Existing `.svo2` captures remain supported for viewing/export. This choice is controlled by `RECORDING_SVO_VERSION` in `zed_capture/config.py` and should be revalidated before changing it.
- **Saved Media** lists completed captures. Select a photo for its saved PNG/depth preview. Click **Review selected SVO**, or double-click an item, to recompute depth and display its 3D point cloud.
- SVO review starts paused at its first frame. Use **Play / Pause** and the frame slider to review a video. Press Play at the end to restart.
- **Back to live** at the bottom (or **Ctrl+L**) returns from saved media to live capture. You can also click **Take new photo** or **Record new video** directly while reviewing: the app reconnects, waits for a fresh live frame, and performs your chosen action automatically. You do not need to click Connect live first. A failed reconnect cancels the pending action.
- Select a video and click **Export selected video to MP4** for a conventional left-camera video saved beside its SVO. MP4 does not preserve stereo, metric depth, or sensor data; keep the SVO as the original.
- Quality-first defaults: **HD2K, 15 FPS, NEURAL_PLUS**. On ZED 2i this is **2208 × 1242 pixels per eye**, the highest supported output resolution. Photos, metric depth, and PLY exports use the full capture resolution. Only the on-screen preview is reduced in size. These settings prioritize detail over frame rate; they do not guarantee depth accuracy for every scene.
- Resolution, FPS, and depth-mode choices apply on the next **Connect live / Back to live**. Manually choosing a smaller resolution also reduces saved photo resolution. The SDK may select a supported FPS for the requested resolution. The status line and each capture's metadata report the actual active settings.
- Stop recording before taking a photo: each photo gets its own separate SVO, and the SDK has one active recorder per camera.

## Automatic camera controls and close-ups

The default **Close-up (30–100 cm)** profile keeps HD2K/15 FPS/NEURAL_PLUS and uses a **0.2–2 m depth window**. Its 3D Reset view is centered around 65 cm instead of 3 m. Depth coloring uses the active profile's range. Choose **General / room** for the previous 0.2–20 m window and wider 3D framing. The minimum cutoff was already 0.2 m; this profile changes framing and excludes the distant background, not the lens or the stereo hardware's physical minimum distance.

On every live connection, **Auto white balance** and **Auto exposure / gain** are explicitly enabled and read back from the camera. **Meter center** uses the central 60% of the image for automatic exposure on both lenses. Keep the subject there; uncheck it for full-frame metering when the subject is off-center. Click **Apply tuning** after changing these choices. Tuning cannot be changed during a recording. Changing the depth profile reopens the source; recorded SVO image colors cannot be re-white-balanced using camera controls.

The app allows one second of live frames for automatic controls to adjust after connecting or applying tuning. This is a settling interval, not a convergence guarantee. Unchecking an auto control holds manual mode using the camera's current values; there are no manual exposure/Kelvin sliders. Brightness, contrast, saturation, sharpness and gamma are left unchanged. Readbacks (including auto flags, exposure, gain, and white-balance temperature), metering area, and depth range are saved in capture metadata. Videos include start/end control snapshots, not per-frame exposure logs.

The ZED 2i has factory-set fixed focus, so the SDK has no autofocus control. For 30–100 cm subjects, use even lighting, visible surface texture, and a subject visible to both lenses. The software does not guarantee accurate depth at the closest end of this range. Fill mode stays disabled and saturated areas stay excluded from depth; missing geometry is not filled simply to make the view look complete. See the [official camera controls](https://docs.stereolabs.com/docs/development/zed-sdk/modules/camera/camera-controls), [depth settings](https://docs.stereolabs.com/docs/development/zed-sdk/modules/depth-sensing/depth-settings), and [StereoLabs fixed-focus explanation](https://community.stereolabs.com/t/technical-details-of-zed-mini-zed-2i/10824).

## 3D view

The embedded OpenGL panel displays the ZED SDK's **XYZRGBA colored point cloud**, with the same basic navigation as ZED Depth Viewer: left drag to orbit, right drag to pan, and scroll to zoom. It includes depth coloring, confidence filtering, an optional 1 m grid, and Reset view. The preview cloud is retrieved at up to 640 pixels wide for interactive rendering; saved photo PLY files use full capture resolution.

**ZED Depth Viewer ↗** opens the actual StereoLabs application in a separate window for its native rendering and full controls. This releases camera access from ZED Capture. Close Depth Viewer before reconnecting here.

For a selected/reviewed SVO, the button copies its path to the clipboard. In Depth Viewer, click the **SVO source icon** and paste that path into the file picker. Tested SDK 5.3.1 does not load a positional SVO filename from its command line. The embedded view is a custom SDK point-cloud renderer; it is not an embedded copy of the proprietary Depth Viewer UI.

The grid is a visual reference 1 m below the camera, not an estimated floor. The app does not perform SLAM or accumulate a spatial map. Coordinates are camera-relative, meters, `RIGHT_HANDED_Y_UP` in saved data.

## Data folder

```text
data/
  photos/<timestamp_unique_id>/
    left.png              # rectified color image
    right.png
    raw_left.png          # original unrectified stereo data
    raw_right.png
    frame.svo            # one lossless stereo frame + available sensor data
    depth_preview.png     # colored visualization, not metric depth
    depth_m.npy           # float32 depth in meters; NaN/Inf = invalid
    cloud.ply             # full-resolution colored 3D points, meters
    metadata.json         # actual camera settings, timestamp, SDK, serial
  recordings/<timestamp_unique_id>/
    recording.svo
    thumbnail.png
    metadata.json
    left_video.mp4        # created when you request MP4 export
  logs/app.log
```

Only folders with completed `metadata.json` appear in the library. If saving fails, incomplete files are retained for inspection instead of being presented as successful captures. Do not move a media folder's individual files apart. Entire capture folders can be copied together. `--data-dir PATH` changes the data location; the default is always this project's `data`, regardless of PyCharm's working directory.

SVO stores unrectified camera images and sensor data. Rectification, depth, and 3D are computed again on playback, so derived results can vary with calibration, SDK version, and processing settings. The saved PNG/depth/PLY files preserve the derived outputs from capture time. Keep the camera's calibration file when transferring recordings to another machine; SVO playback normally resolves calibration using the camera serial number.

Example depth loading:

```python
import numpy as np
depth = np.load("data/photos/<capture_id>/depth_m.npy")
valid_depth = depth[np.isfinite(depth)]
```

## GitHub / portable project

All application code, pinned Python dependencies, setup scripts, tests, and the shared Windows PyCharm configuration are in this repository. Setup selects the `pyzed` build supplied by the installed SDK instead of committing a machine-specific wheel or DLL.

`.gitignore` excludes virtualenvs, camera captures, logs, temporary exports, local IDE state, and `.env` files. The empty data directory is preserved by `data/.gitkeep`; all required subfolders are recreated on launch. Your existing local captures can remain in `data` while you publish the code.

From the repository root, the usual upload workflow is `git add .`, commit, add your own GitHub remote, and push. This project does not configure a remote or publish anything automatically. A fresh clone runs with the terminal/PyCharm instructions above once its native prerequisites are installed.

## Troubleshooting

If the camera is missing, check USB 3 connectivity and close ZED Explorer, Depth Viewer, Studio, and other instances of this app. NEURAL models may require an initial SDK model download/optimization. A scene with little texture or blocked lenses can cause a self-calibration warning and unreliable depth; that is not a recording-format failure.

`CAMERA STREAM FAILED TO START` can occur when another application already owns the camera. Check for an earlier capture window (including one behind PyCharm), close it normally, then click Back to live or rerun the app. If no application owns the camera, check the USB 3 connection. The single-instance guard prevents duplicate launches of this version from competing for it.

On one tested legacy SVO, the SDK advertised 20 frames but sequential playback returned 19. MP4 export now checks this count and reports a failure instead of claiming a complete export; the partial MP4 is retained with `.partial.mp4` and the original SVO is unchanged. This SDK readback discrepancy has not been resolved by the camera tuning.

The app explicitly disables the optional old `OpenGL_accelerate` extension installed by the ZED 5.3 Windows helper because it is incompatible with NumPy 2. Rendering still uses the GPU through PyOpenGL.

## Checks

Run `python -m unittest discover -s tests -v` using the project interpreter. This tests media-library integrity, unique capture folders, packed RGBA decoding/invalid-point filtering, latest-frame delivery, and camera cleanup after a finalization error.

`tests/hardware_check.py --data-dir PATH` is an opt-in hardware check: it opens the camera, takes a photo, records a short video, verifies raw stereo equality with the photo SVO, regenerates depth/3D, seeks in the video, and exports/decodes MP4. Close other camera apps before running it. It writes real camera data to the specified directory.

The regression tests include media-library integrity, RGBA decoding, cleanup, returning from review for a new photo/video, waiting for a fresh live frame, and cancelling a pending capture after connection failure. The GitHub Actions workflow runs the tests without a camera or SDK. Real hardware checks remain separate and opt-in. Long recordings, unplug/reconnect during recording, Linux hardware, and every resolution/depth preset need separate validation.

See `VALIDATION.md` for the actual local checks, full-resolution hardware results, source-only setup check, and tested limits.

Official references: [ZED 2i specifications](https://docs.stereolabs.com/docs/products/cameras/zed/specifications), [Recording and SVO contents](https://docs.stereolabs.com/docs/development/zed-sdk/modules/camera/recording), [ZED Depth Viewer](https://docs.stereolabs.com/docs/development/zed-tools/zed-depth-viewer).
