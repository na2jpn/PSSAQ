import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
import wave
import numpy as np
from PySide6 import QtCore,QtGui,QtTest,QtWidgets
from pssaq.dsp import SAQProcessor,spectrum,RATE,TUNE_MIN,TUNE_MAX
from pssaq.gui import MainWindow
from pssaq.storage import load_settings
from pssaq.resources import asset_path
from pssaq.window_icon import persist_taskbar_icon


class TuningDSPTests(unittest.TestCase):
    def test_tuning_moves_both_bandpass_and_monitor_mixer(self):
        t=np.arange(RATE)/RATE
        x=.1*np.sin(2*np.pi*17380*t)
        processor=SAQProcessor(bandwidth=50)
        _,_,before=processor.process(x)
        processor.set_carrier(17380)
        _,env,after=processor.process(x)
        f,db=spectrum(after[RATE//2:])
        self.assertAlmostEqual(f[np.argmax(db)],700,delta=3)
        self.assertGreater(np.median(env[RATE//2:]),.06)
        self.assertGreater(np.std(after[RATE//2:]),np.std(before[RATE//2:])*40)

    def test_limits_and_unchanged_tuning_preserve_state(self):
        a,b=SAQProcessor(),SAQProcessor()
        x=np.random.default_rng(23).normal(size=8192)
        a.process(x[:2048]);b.process(x[:2048]);a.set_carrier(17200)
        np.testing.assert_array_equal(a.process(x[2048:])[2],b.process(x[2048:])[2])
        a.set_carrier(15000);self.assertEqual(a.carrier,TUNE_MIN)
        a.set_carrier(20000);self.assertEqual(a.carrier,TUNE_MAX)
        with self.assertRaises(ValueError):a.set_carrier(float('nan'))


class TuningUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_mouse_drag_keyboard_reset_and_saved_frequency(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False);window.timer.stop();window.show();self.app.processEvents()
            try:
                plot=window.fft;y=plot.height()//2
                QtTest.QTest.mousePress(plot,QtCore.Qt.LeftButton,pos=QtCore.QPoint(round(plot.frequency_x(17200)),y))
                QtTest.QTest.mouseMove(plot,QtCore.QPoint(round(plot.frequency_x(17350)),y))
                QtTest.QTest.mouseRelease(plot,QtCore.Qt.LeftButton,pos=QtCore.QPoint(round(plot.frequency_x(17350)),y))
                self.assertAlmostEqual(window.proc.carrier,17350,delta=1)
                self.assertEqual(plot.carrier,window.proc.carrier)
                start=window.proc.carrier
                QtTest.QTest.keyClick(plot,QtCore.Qt.Key_Right)
                self.assertEqual(window.proc.carrier,start+1)
                QtTest.QTest.keyClick(plot,QtCore.Qt.Key_Left,QtCore.Qt.ShiftModifier)
                self.assertEqual(window.proc.carrier,start-9)
                self.assertEqual(load_settings(tmp)['carrier'],window.proc.carrier)
                selected=window.proc.carrier
                window.change_language('ru')
                self.assertIn(f'{selected/1000:.3f}',window.frequency_label.text())
                self.assertIn(f'{selected/1000:.3f}',window.wave_title.text())
                QtTest.QTest.mouseDClick(plot,QtCore.Qt.LeftButton,pos=QtCore.QPoint(20,y))
                self.assertEqual(window.proc.carrier,17200)
                self.assertEqual(load_settings(tmp)['carrier'],17200)
                QtTest.QTest.mouseClick(plot,QtCore.Qt.LeftButton,pos=QtCore.QPoint(round(plot.frequency_x(16900)),y))
                selected=window.proc.carrier
                self.assertAlmostEqual(selected,16900,delta=1)
            finally:window.close()
            restored=MainWindow(tmp,auto_start=False)
            try:
                self.assertEqual(restored.proc.carrier,selected)
                self.assertEqual(restored.fft.carrier,selected)
                self.assertIn(f'{selected/1000:.3f}',restored.frequency_label.text())
            finally:restored.close()

    def test_retuning_preserves_recording_decoded_text_and_user_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False);window.timer.stop()
            try:
                window.bandwidth.setCurrentIndex(window.bandwidth.findData(100))
                window.nr.setCurrentIndex(1);window.toggle_record();recorder=window.recorder
                window.decoded.setPlainText('VVV DE SAQ')
                raw=np.random.default_rng(4).normal(0,.02,4096).astype(np.float32)
                window.q.put(raw);window.tick()
                window.tune_frequency(17380)
                self.assertIs(window.recorder,recorder)
                self.assertEqual(window.decoded.toPlainText(),'VVV DE SAQ')
                self.assertEqual(window.bandwidth.currentData(),100)
                self.assertEqual(window.nr.currentData(),1)
                self.assertIsNone(window.input_stream)
                self.assertTrue(window.outq.empty())
                window.q.put(raw);window.tick();window.toggle_record()
                path=next((Path(tmp)/'recdata').glob('*.wav'))
                with wave.open(str(path)) as f:pcm=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
                np.testing.assert_array_equal(pcm,np.tile((raw*32768).astype('<i2'),2))
            finally:window.close()

    def test_about_and_application_use_same_new_artwork(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False);window.timer.stop()
            try:
                expected=QtGui.QImage(str(asset_path('pssaq.png')))
                def inspect(dialog):
                    doc=dialog.findChild(QtWidgets.QTextBrowser).document()
                    self.assertEqual(doc.resource(QtGui.QTextDocument.ImageResource,QtCore.QUrl('pssaq-icon')),expected)
                    actual=window.windowIcon().pixmap(256,256).toImage()
                    reference=QtGui.QPixmap.fromImage(expected).scaled(256,256,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation).toImage()
                    self.assertEqual(actual,reference)
                    return 0
                with patch.object(QtWidgets.QDialog,'exec',inspect):window.about()
            finally:window.close()

    def test_icon_cache_uses_content_name_and_removes_only_managed_old_icons(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'config';folder.mkdir()
            (folder/'pssaq_taskbar.ico').write_bytes(b'old')
            (folder/'pssaq_taskbar_000000000000.ico').write_bytes(b'old')
            custom=folder/'pssaq_taskbar_custom.ico';custom.write_bytes(b'keep')
            icon=persist_taskbar_icon(tmp)
            self.assertRegex(icon.name,r'^pssaq_taskbar_[0-9a-f]{12}\.ico$')
            self.assertEqual(icon.read_bytes(),asset_path('pssaq.ico').read_bytes())
            self.assertFalse((folder/'pssaq_taskbar.ico').exists())
            self.assertFalse((folder/'pssaq_taskbar_000000000000.ico').exists())
            self.assertEqual(custom.read_bytes(),b'keep')
