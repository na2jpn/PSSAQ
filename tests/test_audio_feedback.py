import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave
import numpy as np
from PySide6 import QtTest, QtWidgets
from pssaq.audio_feedback import output_chime
from pssaq.dsp import RATE, spectrum
from pssaq.gui import MainWindow, SettingsDialog


class FakeStream:
    active=False
    def start(self):self.active=True
    def stop(self):self.active=False
    def close(self):self.active=False


class AudioFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.window=MainWindow(root=self.tmp.name,auto_start=False)
        self.window.timer.stop()
        self.window.mute.setChecked(True)
        self.window.cfg['output']=7
        self.stream=FakeStream()
        self.audio=SimpleNamespace(
            query_devices=Mock(return_value={'max_output_channels':2}),
            OutputStream=Mock(return_value=self.stream))
        self.patcher=patch('pssaq.gui.sd',self.audio)
        self.patcher.start()

    def tearDown(self):
        self.window.close()
        self.patcher.stop()
        self.tmp.cleanup()

    def test_slider_plays_once_on_selected_output_with_rx_muted(self):
        self.window.volume.setValue(80)
        self.window.volume.setValue(40)
        self.audio.OutputStream.assert_not_called()
        QtTest.QTest.qWait(230)
        self.audio.OutputStream.assert_called_once()
        args=self.audio.OutputStream.call_args.kwargs
        self.assertEqual(args['device'],7)
        self.assertEqual(args['channels'],2)
        out=np.zeros((2048,2),dtype=np.float32)
        args['callback'](out,len(out),None,None)
        self.assertGreater(float(np.max(np.abs(out))),.08)
        self.assertLessEqual(float(np.max(np.abs(out))),.22*.4+1e-6)
        np.testing.assert_array_equal(out[:,0],out[:,1])
        self.assertTrue(self.window.mute.isChecked())

    def test_chime_duration_and_two_notes(self):
        chime=output_chime()
        self.assertEqual(len(chime),round(.24*RATE))
        for part,hz in ((chime[:round(.09*RATE)],880),(chime[round(.09*RATE):],1320)):
            f,db=spectrum(part)
            self.assertAlmostEqual(float(f[np.argmax(db)]),hz,delta=12)
            self.assertAlmostEqual(float(part[0]),0,delta=1e-7)
            self.assertAlmostEqual(float(part[-1]),0,delta=1e-7)

    def test_variable_callback_sizes_keep_tone_continuous_and_return_to_mute(self):
        self.window.play_output_test()
        blocks=[]
        for count in (511,2048,3300,7000):
            out=np.empty((count,2),dtype=np.float32)
            self.window.output_cb(out,count,None,None)
            blocks.append(out[:,0])
        expected=np.pad(output_chime()*.5,(0,sum(map(len,blocks))-len(output_chime())))
        np.testing.assert_allclose(np.concatenate(blocks),expected,atol=1e-7)
        self.assertTrue(self.window.muted_out)

    def test_zero_volume_and_unselected_output_are_explained(self):
        self.window.volume.setValue(0)
        self.window.play_output_test()
        self.audio.OutputStream.assert_not_called()
        self.assertIn('0%',self.window.statusBar().currentMessage())
        self.window.volume.setValue(50)
        self.window.cfg['output']=None
        self.window.play_output_test()
        self.audio.OutputStream.assert_not_called()
        self.assertIn('未選択',self.window.statusBar().currentMessage())

    def test_open_failure_shows_error(self):
        self.audio.OutputStream.side_effect=RuntimeError('device busy')
        self.window.play_output_test()
        self.assertIn('device busy',self.window.statusBar().currentMessage())
        self.assertTrue(self.window.testq.empty())

    def test_check_sound_does_not_enter_recording(self):
        self.window.bandwidth.setCurrentIndex(self.window.bandwidth.findData(50))
        self.window.nr.setCurrentIndex(3)
        self.window.toggle_record()
        self.window.play_output_test()
        self.window.q.put(np.zeros(4096,dtype=np.float32))
        self.window.tick()
        out=np.empty((4096,2),dtype=np.float32)
        self.window.output_cb(out,len(out),None,None)
        self.assertGreater(float(np.max(np.abs(out))),0)
        self.window.toggle_record()
        path=next((Path(self.tmp.name)/'recdata').glob('*.wav'))
        with wave.open(str(path)) as w:
            pcm=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
        self.assertEqual(len(pcm),4096)
        self.assertFalse(np.any(pcm))

    def test_hostapi_labels_keep_device_ids(self):
        self.audio.query_hostapis=Mock(return_value=[{'name':'MME'},{'name':'Windows DirectSound'}])
        self.audio.query_devices=Mock(return_value=[
            {'name':'UAB-80-IN','hostapi':0,'max_input_channels':1,'max_output_channels':0},
            {'name':'UAB-80-IN','hostapi':1,'max_input_channels':1,'max_output_channels':0}])
        dlg=SettingsDialog({'input':1},self.window)
        self.assertIn('[MME]',dlg.inputs.itemText(1))
        self.assertIn('[Windows DirectSound]',dlg.inputs.itemText(2))
        self.assertEqual(dlg.inputs.currentData(),1)
        dlg.close()
