import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import unittest
from PySide6 import QtGui, QtWidgets
from pssaq.resources import asset_path
from pssaq.selftest import run
from pssaq.gui import MainWindow
from pssaq.storage import save_settings


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setWindowIcon(QtGui.QIcon(str(asset_path('pssaq.ico'))))

    def test_end_to_end_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'report.json'
            self.assertEqual(run(self.app, report), 0, report.read_text(encoding='utf-8') if report.exists() else '')
            self.assertTrue(json.loads(report.read_text(encoding='utf-8'))['ok'])

    def test_saved_speed_label_and_no_audio_during_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_settings({'wpm': 25}, tmp)
            window = MainWindow(root=tmp, auto_start=False)
            self.assertEqual(window.speedtext.text(), '25 WPM')
            self.app.processEvents()
            self.assertIsNone(window.input_stream)
            window.close()

    def test_icon_sizes(self):
        icon = QtGui.QIcon(str(asset_path('pssaq.ico')))
        for size in (16, 32, 48, 256):
            self.assertFalse(icon.pixmap(size, size).isNull())
