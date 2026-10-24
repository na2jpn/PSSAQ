import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
import wave
import numpy as np
from PySide6 import QtWidgets
from pssaq.dsp import SAQProcessor, RATE
from pssaq.gui import MainWindow
from pssaq.noise_reduction import MonitorNoiseReducer


class ReceiverFilterTests(unittest.TestCase):
    def test_bandwidth_passes_carrier_and_rejects_nearby_interference(self):
        t = np.arange(RATE) / RATE
        def rms(width, frequency):
            processor = SAQProcessor()
            processor.set_bandwidth(width)
            _, _, audio = processor.process(.1 * np.sin(2*np.pi*frequency*t))
            return np.sqrt(np.mean(audio[RATE//2:]**2))
        self.assertGreater(rms(100, 17200), .06)
        self.assertGreater(rms(500, 17350), rms(100, 17350)*50)

    def test_unchanged_bandwidth_does_not_reset_filter_state(self):
        x = np.random.default_rng(7).normal(size=8192)
        a, b = SAQProcessor(), SAQProcessor()
        a.process(x[:2048]);b.process(x[:2048])
        a.set_bandwidth(220)
        np.testing.assert_array_equal(a.process(x[2048:])[2], b.process(x[2048:])[2])

    def test_nr_off_is_exact_bypass_and_toggle_discards_old_audio(self):
        nr = MonitorNoiseReducer()
        x = np.random.default_rng(2).normal(size=4096).astype(np.float32)
        np.testing.assert_array_equal(nr.process(x), x)
        nr.set_level(3);nr.process(x)
        nr.set_level(0)
        np.testing.assert_array_equal(nr.process(np.zeros(100)), np.zeros(100))
        nr.set_level(2)
        np.testing.assert_array_equal(nr.process(np.zeros(4096)), np.zeros(4096))

    def test_nr_streaming_with_arbitrary_block_sizes_matches_whole_input(self):
        x = np.random.default_rng(3).normal(0, .05, 13000).astype(np.float32)
        for level in (1, 2, 3):
            with self.subTest(level=level):
                expected = MonitorNoiseReducer(level).process(x)
                nr = MonitorNoiseReducer(level)
                sizes = [1, 17, 384, 1536, 2001, 2048, 4093, 2920]
                self.assertEqual(sum(sizes), len(x))
                parts = [];start = 0
                for size in sizes:
                    part = nr.process(x[start:start+size]);start += size
                    self.assertEqual(len(part), size)
                    parts.append(part)
                actual = np.concatenate(parts)
                self.assertTrue(np.all(np.isfinite(actual)))
                np.testing.assert_array_equal(actual, expected)

    def test_nr_improves_tone_to_noise_ratio_for_simulated_noisy_cw(self):
        t = np.arange(RATE*3) / RATE
        x = .025*np.sin(2*np.pi*17200*t) + np.random.default_rng(17).normal(0, .3, len(t))
        _, _, audio = SAQProcessor().process(x)
        clean = MonitorNoiseReducer(2).process(audio)
        def snr(y):
            y = y[RATE:]
            tt = np.arange(len(y))/RATE
            basis = np.column_stack((np.sin(2*np.pi*700*tt), np.cos(2*np.pi*700*tt)))
            tone = basis @ np.linalg.lstsq(basis, y, rcond=None)[0]
            return 10*np.log10(np.mean(tone*tone) / np.mean((y-tone)**2))
        self.assertGreater(snr(clean), snr(audio)+1)
        # A strong continuous carrier must not be learned as noise and erased.
        _, _, tone = SAQProcessor().process(.1*np.sin(2*np.pi*17200*t))
        reduced = MonitorNoiseReducer(3).process(tone)
        self.assertGreater(np.std(reduced[RATE:]), np.std(tone[RATE:])*.9)


class ReceiverFilterUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_controls_preserve_raw_recording_and_language_switch_then_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(tmp, auto_start=False);window.timer.stop()
            try:
                window.toggle_record();recorder = window.recorder
                window.bandwidth.setCurrentIndex(window.bandwidth.findData(100))
                window.nr.setCurrentIndex(3)
                self.assertEqual(window.proc.bandwidth, 50)
                self.assertEqual(window.nr_proc.level, 3)
                window.decoded.setPlainText('VVV DE SAQ')
                window.change_language('ru')
                self.assertEqual(window.nr.currentText(), 'Сильный')
                self.assertEqual(window.bandwidth.currentData(), 100)
                self.assertEqual(window.decoded.toPlainText(), 'VVV DE SAQ')
                self.assertIs(window.recorder, recorder)
                raw = np.random.default_rng(8).normal(0, .02, 4096).astype(np.float32)
                expected_env = SAQProcessor(bandwidth=50).process(raw)[1][::24]
                window.q.put(raw);window.tick()
                np.testing.assert_allclose(window.wave.data, expected_env)
                window.toggle_record()
                path = next((Path(tmp)/'recdata').glob('*.wav'))
                with wave.open(str(path)) as w:
                    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
                np.testing.assert_array_equal(pcm, (raw*32768).astype('<i2'))
            finally:
                window.close()
            restored = MainWindow(tmp, auto_start=False)
            try:
                self.assertEqual(restored.bandwidth.currentData(), 100)
                self.assertEqual(restored.nr.currentData(), 3)
                self.assertEqual(restored.proc.bandwidth, 50)
                self.assertEqual(restored.nr_proc.level, 3)
            finally:
                restored.close()
