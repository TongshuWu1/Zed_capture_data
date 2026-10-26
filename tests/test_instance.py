import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
import uuid
from PySide6.QtWidgets import QApplication
from zed_capture.instance import SingleInstance


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.name = "zed-capture-test-" + uuid.uuid4().hex
        self.instances = []

    def tearDown(self):
        for instance in reversed(self.instances):
            instance.close()
        self.app.processEvents()
        self.temp.cleanup()

    def guard(self):
        guard = SingleInstance(self.name, self.temp.name)
        self.instances.append(guard)
        return guard

    def test_second_instance_reuses_owner_instead_of_acquiring_camera(self):
        owner, duplicate = self.guard(), self.guard()
        activated = []
        owner.activation_requested.connect(lambda: activated.append(True))
        self.assertTrue(owner.acquire())
        self.assertFalse(duplicate.acquire())
        for _ in range(10):
            self.app.processEvents()
            if activated:
                break
        self.assertEqual(activated, [True])
        self.assertFalse(duplicate.owns_lock)

    def test_normal_exit_allows_next_launch(self):
        owner = self.guard()
        self.assertTrue(owner.acquire())
        owner.close()
        self.assertTrue(self.guard().acquire())
