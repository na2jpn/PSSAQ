import unittest
import numpy as np
from pssaq.dsp import SAQProcessor, spectrum, MorseDecoder, RATE

class DSPTests(unittest.TestCase):
    def test_downconvert(self):
        p=SAQProcessor()
        t=np.arange(RATE)/RATE
        x=.1*np.sin(2*np.pi*17200*t)
        _,en,au=p.process(x)
        f,d=spectrum(au[10000:])
        self.assertAlmostEqual(f[np.argmax(d)],700,delta=3)
        self.assertGreater(np.median(en[10000:]),.04)
    def test_offfrequency_attenuated(self):
        def measure(hz):
            p=SAQProcessor()
            t=np.arange(RATE)/RATE
            _,en,_=p.process(.1*np.sin(2*np.pi*hz*t))
            return np.median(en[20000:])
        self.assertGreater(measure(17200),measure(15000)*50)
    def test_spectrum(self):
        t=np.arange(48000)/48000
        f,d=spectrum(np.sin(2*np.pi*17200*t))
        self.assertAlmostEqual(f[np.argmax(d)],17200,delta=1)
    def test_morse_table(self):
        from pssaq.dsp import MORSE
        self.assertEqual(MORSE['...'],'S')
        self.assertEqual(MORSE['.-'],'A')

if __name__=='__main__':unittest.main()
