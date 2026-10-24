"""Exercise actual imports, DSP and the window without opening audio hardware."""
import json
import tempfile
import traceback
from pathlib import Path
import numpy as np
from PySide6 import QtGui
from . import __version__
from .dsp import RATE, spectrum
from .gui import MainWindow, sd, AUDIO_IMPORT_ERROR
from .resources import asset_path, license_path


def run(app, report=None):
    result = {'version': __version__, 'ok': False}
    window = None
    try:
        assert sd is not None, 'Audio library failed to load: ' + AUDIO_IMPORT_ERROR
        assert asset_path('apply_update.ps1').is_file(), 'Update helper is missing'
        assert license_path().is_file(), 'Common licence is missing'
        with tempfile.TemporaryDirectory(prefix='pssaq-check-') as tmp:
            window = MainWindow(root=tmp, auto_start=False)
            window.timer.stop()
            window.show()
            app.processEvents()
            assert not window.windowIcon().isNull(), 'Window icon is missing'
            assert not app.windowIcon().isNull(), 'Application icon is missing'
            assert not window.windowIcon().pixmap(32, 32).isNull(), 'Icon cannot be rendered'
            assert not QtGui.QImage(str(asset_path('pssaq.png'))).isNull(), 'About icon is missing'
            assert not window.centralWidget().artwork.isNull(), 'SAQ background artwork is missing'
            for code, label in (('en', 'Test OUT'), ('ru', 'Тест OUT'), ('ja', '出力テスト')):
                window.change_language(code)
                assert window.output_test.text() == label, 'Language catalogue is missing: ' + code
                assert (Path(tmp) / 'language' / (code + '.json')).is_file()
            window.toggle_record()
            t = np.arange(RATE) / RATE
            signal = (.1 * np.sin(2 * np.pi * 17200 * t)).astype(np.float32)
            audio = []
            for i in range(0, RATE, 2048):
                window.q.put(signal[i:i + 2048])
                window.tick()
                audio.append(window.outq.get_nowait())
            window.toggle_record()
            f, db = spectrum(np.concatenate(audio)[10000:])
            peak = float(f[np.argmax(db)])
            assert abs(peak - 700) < 3, f'Unexpected monitor frequency: {peak}'
            assert len(window.fft.data) > 0 and len(window.wave.data) > 0
            window.bandwidth.setCurrentIndex(window.bandwidth.findData(100))
            window.nr.setCurrentIndex(2)
            assert window.proc.bandwidth == 50 and window.nr_proc.level == 2
            filtered = []
            for i in range(0, RATE, 2048):
                window.q.put(signal[i:i + 2048])
                window.tick()
                filtered.append(window.outq.get_nowait())
            filtered = np.concatenate(filtered)
            assert np.all(np.isfinite(filtered)) and np.max(np.abs(filtered)) > .01, 'NR output is invalid'
            window.save_frequency(17380)
            shifted=(.1*np.sin(2*np.pi*17380*t)).astype(np.float32)
            tuned=[]
            for i in range(0,RATE,2048):
                window.q.put(shifted[i:i+2048]);window.tick()
                tuned.append(window.outq.get_nowait())
            f,db=spectrum(np.concatenate(tuned)[RATE//2:])
            tuned_peak=float(f[np.argmax(db)])
            assert abs(tuned_peak-700)<3,'Tuning did not move the mixer'
            assert window.fft.carrier==17380 and '17.380' in window.frequency_label.text()
            window.testq.put(window._chime)
            check_audio=np.zeros((2048,2),dtype=np.float32)
            window.output_cb(check_audio,len(check_audio),None,None)
            assert np.max(np.abs(check_audio))>0, 'Output check sound is silent'
            window.transcript.append('PSSAQ startup test')
            assert list((Path(tmp) / 'recdata').glob('*.wav'))
            assert list((Path(tmp) / 'masterdata').glob('*_ALL.txt'))
            frame = QtGui.QPixmap(window.size())
            window.render(frame)
            assert not frame.isNull()
            window.close()
            app.processEvents()
            window = None
            result.update(ok=True, monitor_hz=peak,
                          checks=['imports', 'icon', 'window', 'FFT', 'DSP', 'recording', 'transcript', 'output chime', 'languages', 'BW', 'NR', 'tuning'])
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if window is not None:
            window.close()
        if report:
            Path(report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def run_icon(app,report=None):
    """Windows build check with a real HWND, never audio or installed data."""
    from .window_icon import install_taskbar_identity
    result={'version':__version__,'ok':False}
    window=None
    try:
        with tempfile.TemporaryDirectory(prefix='pssaq-icon-check-') as tmp:
            window=MainWindow(root=tmp,auto_start=False);window.timer.stop()
            identity=install_taskbar_identity(window)
            assert identity is not None,'Windows taskbar identity could not be initialized'
            window.show();app.processEvents();identity.apply();app.processEvents()
            assert identity.verify(),'Windows icon/property check failed: '+identity.error
            result.update(ok=True,checks=['native window icons','taskbar app ID','persistent taskbar icon','relaunch command'])
            window.close();app.processEvents();window=None
    except Exception:
        result['error']=traceback.format_exc()
    finally:
        if window is not None:window.close()
        if report:Path(report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['ok'] else 1
