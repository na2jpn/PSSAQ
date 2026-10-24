import tempfile, wave, unittest, datetime
from pathlib import Path
import numpy as np
from pssaq.storage import Recorder, Transcript, load_settings, save_settings
class StorageTests(unittest.TestCase):
    def test_record(self):
        with tempfile.TemporaryDirectory() as d:
            r=Recorder(d,now=datetime.datetime(2026,10,24,21,30,0));r.write(np.array([0,.5,-.5]));r.close()
            self.assertEqual(r.path.name,'20261024-213000.wav')
            with wave.open(str(r.path)) as w:
                self.assertEqual(w.getframerate(),48000)
                self.assertEqual(w.getnframes(),3)
    def test_transcript(self):
        with tempfile.TemporaryDirectory() as d:
            t=Transcript(d);now=datetime.datetime(2026,10,24,22,0)
            t.append('SAQ',now);t.append(' TEST',now)
            self.assertIn('SAQ TEST',(Path(d)/'masterdata/20261024_ALL.txt').read_text(encoding='utf-8'))
    def test_config(self):
        with tempfile.TemporaryDirectory() as d:
            save_settings({'mute':True},d)
            self.assertTrue(load_settings(d)['mute'])
if __name__=='__main__':unittest.main()
