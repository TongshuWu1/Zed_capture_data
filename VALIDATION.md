# Validation — October 26, 2026

Tested locally on Windows with Python 3.11, ZED SDK 5.3.1, an RTX 4080, and a connected ZED 2i.

- Eleven regression tests passed, including review-to-capture transitions, cancellation after reconnect failure, and normalized playback positions for both legacy SVO and SVO2.
- `pip check` and Python compilation checks passed.
- The hardware check opened **HD2K at 15 FPS with NEURAL_PLUS**, saved **2208 × 1242** images per eye, and recorded/replayed a **19-frame lossless video**.
- The photo SVO contained exactly one frame. Both unrectified PNGs matched legacy SVO replay pixel for pixel over the complete image. Metric depth and 3D replay also passed.
- All exported MP4 frames decoded at the expected resolution. MP4 is a viewing export; the lossless SVO and PNGs remain the quality originals.
- A real UI/worker integration check passed saved-media review → new photo, review → new video recording, and the Back to live button. These actions reconnected the camera automatically at the quality defaults.
- Existing capture files were copied to the new project's `data` folder without changes. They are excluded from Git.
- A source-only ZIP was extracted into a separate directory without a virtualenv, local IDE files, or captures. `py -3.11 run.py --setup-only` created a new environment and installed the SDK-matched API successfully; all eleven tests passed there, and a repeated setup-only launch reused the prepared environment.

## Startup contention fix

An earlier test UI remained running and held the camera while a second PyCharm launch reported `CAMERA STREAM FAILED TO START`. The idle test window was closed through its normal close handler, its processes exited, and the camera subsequently opened successfully at HD2K/15 FPS/NEURAL_PLUS, delivered color/depth/3D, and was closed again.

A per-user single-instance guard now acquires an OS lock before constructing the capture UI. A second process asks the owner to raise its existing window and exits without constructing another capture UI. Two new regression tests passed (thirteen total), and a separate two-process check verified duplicate rejection/activation and normal owner exit. No test UI or camera worker was left running after these checks.

An earlier HD2K test using SDK 5.3.1 **SVO2 LOSSLESS** failed strict pixel equality in the last four rows. Repeated playback reproduced the mismatch. The same capture procedure using **legacy lossless SVO** passed full-image equality, so this project records legacy `.svo`. The strict pixel-equality check remains in `tests/hardware_check.py`.

Long recordings, camera unplugging mid-recording, other cameras, other SDK versions, Linux hardware, and other depth/resolution settings have not been validated. The GitHub Actions workflow is included but has not been executed on GitHub during this task.

## Automatic controls / close-up profile

- Nineteen regression tests passed after adding auto-control readback checks, center/full-frame exposure metering tests, and UI tuning state tests.
- On the connected ZED 2i, both auto flags read back as enabled. Both lenses reported exposure ROI `[441, 248, 1325, 745]` at HD2K. Disabling both auto controls and resetting full-frame metering, then re-enabling them with center metering, passed.
- SDK depth-range readback was approximately 0.2–2.0 m for the Close-up profile. Live color/depth/3D retrieval passed, and a new 2208 × 1242 photo with both auto controls enabled matched its one-frame legacy SVO over every raw stereo pixel. Metric depth and 3D replay passed.
- White-balance temperature, exposure, and gain readbacks were obtained; color accuracy was not measured against a gray/color chart. Depth accuracy at measured 30–100 cm distances was not tested. A low-texture/occlusion self-calibration warning occurred during one open, so this is a settings/integrity check, not a calibration certification.
- The broader hardware test did **not** fully pass: a 20-frame legacy video produced 19 sequentially readable/exported frames in the SDK. This was reproduced by reading that SVO again. The MP4 exporter now fails explicitly on an advertised/returned count mismatch, preserving the partial export and original SVO. No frame was fabricated or duplicated to force the count check to pass.
