import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from zed_capture.tuning import apply_auto_controls


class TuningTests(unittest.TestCase):
    def setUp(self):
        names = ("WHITEBALANCE_AUTO", "AEC_AGC", "AEC_AGC_ROI", "WHITEBALANCE_TEMPERATURE",
                 "EXPOSURE", "GAIN", "BRIGHTNESS", "CONTRAST", "SATURATION", "SHARPNESS", "GAMMA")
        self.sl = SimpleNamespace(VIDEO_SETTINGS=SimpleNamespace(**{name: name for name in names}),
            ERROR_CODE=SimpleNamespace(SUCCESS=0), SIDE=SimpleNamespace(BOTH="both"),
            Rect=lambda x,y,w,h: SimpleNamespace(x=x,y=y,width=w,height=h))
        self.camera = Mock()
        self.camera.set_camera_settings.return_value = 0
        self.camera.set_camera_settings_roi.return_value = 0
        self.camera.get_camera_information.return_value = SimpleNamespace(
            camera_configuration=SimpleNamespace(resolution=SimpleNamespace(width=1000,height=600)))
        self.values = {name: 1 for name in names}
        self.camera.get_camera_settings.side_effect = lambda key: (0, self.values[key])

    def test_auto_switches_do_not_accidentally_set_manual_exposure_or_kelvin(self):
        values = apply_auto_controls(self.camera, self.sl)
        calls = self.camera.set_camera_settings.call_args_list
        self.assertEqual([(call.args[0], call.args[1]) for call in calls],
                         [("WHITEBALANCE_AUTO", 1), ("AEC_AGC", 1)])
        roi = self.camera.set_camera_settings_roi.call_args.args[1]
        self.assertEqual([roi.x,roi.y,roi.width,roi.height],[200,120,600,360])
        self.assertEqual(values["exposure_roi_xywh"], [200,120,600,360])
        self.assertFalse(self.camera.set_camera_settings_roi.call_args.kwargs["reset"])

    def test_full_frame_metering_resets_a_previous_roi(self):
        values = apply_auto_controls(self.camera,self.sl,center_metering=False)
        self.assertTrue(self.camera.set_camera_settings_roi.call_args.kwargs["reset"])
        self.assertEqual(values["exposure_roi_xywh"],[0,0,1000,600])

    def test_control_readback_failure_is_not_reported_as_success(self):
        self.values["WHITEBALANCE_AUTO"] = 0
        with self.assertRaisesRegex(RuntimeError,"did not confirm whitebalance_auto"):
            apply_auto_controls(self.camera,self.sl)

    def test_sdk_setting_error_is_reported(self):
        self.camera.set_camera_settings.return_value = 7
        with self.assertRaisesRegex(RuntimeError,"automatic white balance: 7"):
            apply_auto_controls(self.camera,self.sl)
