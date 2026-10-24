import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from PySide6 import QtCore,QtGui,QtTest,QtWidgets
from pssaq.gui import MainWindow
from pssaq.storage import save_settings,load_settings
from pssaq.window_icon import application_icon,persist_taskbar_icon
from pssaq.resources import asset_path


class UIDefaultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_fresh_install_starts_unmuted(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False)
            try:
                self.assertFalse(window.mute.isChecked())
                self.assertFalse(window.muted_out)
            finally:window.close()

    def test_old_muted_setting_migrates_once_then_respects_user_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_settings({'mute':True,'volume':67,'gain':123},tmp)
            window=MainWindow(tmp,auto_start=False)
            try:
                self.assertFalse(window.mute.isChecked())
                self.assertFalse(load_settings(tmp)['mute'])
                self.assertEqual(window.volume.value(),67)
                self.assertEqual(window.gain.value(),123)
                window.mute.setChecked(True)
            finally:window.close()
            restored=MainWindow(tmp,auto_start=False)
            try:
                self.assertTrue(restored.mute.isChecked())
                self.assertTrue(restored.muted_out)
            finally:restored.close()

    def test_checkboxes_are_visible_and_keep_native_mouse_and_keyboard_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False);window.timer.stop();window.show();self.app.processEvents()
            try:
                for box in (window.auto,window.mute):
                    self.assertIsInstance(box,QtWidgets.QCheckBox)
                    box.setChecked(False);box.setFocus();self.app.processEvents()
                    option=QtWidgets.QStyleOptionButton();box.initStyleOption(option)
                    rect=box.style().subElementRect(QtWidgets.QStyle.SE_CheckBoxIndicator,option,box)
                    self.assertGreaterEqual(rect.width(),18)
                    image=box.grab().toImage()
                    self.assertGreater(image.pixelColor(rect.center()).lightness(),220)
                    QtTest.QTest.keyClick(box,QtCore.Qt.Key_Space)
                    self.assertTrue(box.isChecked())
                    image=box.grab().toImage()
                    dark=sum(image.pixelColor(x,y).lightness()<100
                             for y in range(rect.top()+3,rect.bottom()-2)
                             for x in range(rect.left()+3,rect.right()-2))
                    self.assertGreater(dark,12)
                    QtTest.QTest.mouseClick(box,QtCore.Qt.LeftButton,pos=QtCore.QPoint(box.width()-5,box.height()//2))
                    self.assertFalse(box.isChecked())
                self.assertFalse(window.muted_out)
                self.assertTrue(window.speed.isEnabled())
            finally:window.close()

    def test_persistent_taskbar_icon_is_outside_temporary_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_settings({'volume':67},tmp)
            icon=persist_taskbar_icon(tmp)
            self.assertEqual(icon.parent,Path(tmp)/'config')
            self.assertEqual(icon.read_bytes(),asset_path('pssaq.ico').read_bytes())
            self.assertFalse(QtGui.QIcon(str(icon)).pixmap(32,32).isNull())
            self.assertEqual(load_settings(tmp),{'volume':67})
            before=icon.stat().st_mtime_ns
            self.assertEqual(persist_taskbar_icon(tmp),icon)
            self.assertEqual(icon.stat().st_mtime_ns,before)

    def test_application_icon_has_explicit_sizes(self):
        icon=application_icon()
        for size in (16,32,48,128,256):
            self.assertIn(QtCore.QSize(size,size),icon.availableSizes())
            self.assertFalse(icon.pixmap(size,size).isNull())
