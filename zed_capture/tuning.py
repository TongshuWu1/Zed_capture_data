"""Live ISP controls. Never apply camera controls to recorded playback."""


def read_controls(camera, sl):
    values = {}
    for name in ("WHITEBALANCE_AUTO", "AEC_AGC", "WHITEBALANCE_TEMPERATURE",
                 "EXPOSURE", "GAIN", "BRIGHTNESS", "CONTRAST", "SATURATION", "SHARPNESS", "GAMMA"):
        status, value = camera.get_camera_settings(getattr(sl.VIDEO_SETTINGS, name))
        if status <= sl.ERROR_CODE.SUCCESS:
            values[name.lower()] = int(value)
    return values


def apply_auto_controls(camera, sl, auto_white_balance=True, auto_exposure=True, center_metering=True):
    def check(status, operation):
        if status > sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"{operation}: {status}")

    # Setting an explicit Kelvin, GAIN, or EXPOSURE would turn AUTO off. Set
    # the dedicated auto switches instead and leave image style controls alone.
    check(camera.set_camera_settings(sl.VIDEO_SETTINGS.WHITEBALANCE_AUTO, int(auto_white_balance)),
          "Set automatic white balance")
    check(camera.set_camera_settings(sl.VIDEO_SETTINGS.AEC_AGC, int(auto_exposure)),
          "Set automatic exposure / gain")
    size = camera.get_camera_information().camera_configuration.resolution
    width, height = round(size.width * 0.6), round(size.height * 0.6)
    roi = sl.Rect((size.width - width) // 2, (size.height - height) // 2, width, height)
    check(camera.set_camera_settings_roi(sl.VIDEO_SETTINGS.AEC_AGC_ROI, roi,
                                        sl.SIDE.BOTH, reset=not center_metering), "Set exposure metering area")
    values = read_controls(camera, sl)
    for key, expected in (("whitebalance_auto", auto_white_balance), ("aec_agc", auto_exposure)):
        if values.get(key) != int(expected):
            raise RuntimeError(f"Camera did not confirm {key}={int(expected)}")
    values["exposure_metering"] = "center_60_percent" if center_metering else "full_frame"
    values["exposure_roi_xywh"] = ([roi.x, roi.y, roi.width, roi.height] if center_metering
                                    else [0, 0, size.width, size.height])
    return values
