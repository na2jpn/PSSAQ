"""17.2 kHz SAQ receiver DSP; no GUI dependencies."""
from __future__ import annotations
import numpy as np
from scipy import signal

RATE = 48000
CARRIER = 17200.0
TUNE_MIN, TUNE_MAX = 16500, 17900

class SAQProcessor:
    def __init__(self, rate=RATE, carrier=CARRIER, tone=700, bandwidth=110):
        self.rate = rate
        self.carrier = carrier
        self.tone = tone
        self.bandwidth = bandwidth
        self._make_filters()
        self.sample_index = 0

    def _make_filters(self):
        low = max(10, self.carrier - self.bandwidth)
        high = min(self.rate / 2 - 100, self.carrier + self.bandwidth)
        self.bp = signal.butter(4, [low, high], btype='bandpass', fs=self.rate, output='sos')
        self.bp_state = signal.sosfilt_zi(self.bp)*0
        self.lp = signal.butter(4, 1500, fs=self.rate, output='sos')
        self.lp_state = signal.sosfilt_zi(self.lp)*0
        self.env_lp = signal.butter(2, 32, fs=self.rate, output='sos')
        self.env_state = signal.sosfilt_zi(self.env_lp)*0

    def set_tone(self, tone):
        self.tone = float(tone)

    def set_carrier(self, carrier):
        carrier=float(carrier)
        if not np.isfinite(carrier):raise ValueError('Frequency must be finite')
        carrier=float(np.clip(round(carrier),TUNE_MIN,TUNE_MAX))
        if carrier==self.carrier:return
        self.carrier=carrier
        self._make_filters()

    def set_bandwidth(self, width):
        """Set total RF passband width; constructor bandwidth is half-width."""
        half = float(np.clip(width, 50, 1000)) / 2
        if half == self.bandwidth:
            return
        self.bandwidth = half
        self._make_filters()

    def process(self, block, gain=1.0):
        raw = np.asarray(block, dtype=np.float64).reshape(-1)
        x = np.clip(raw * gain, -4, 4)
        filtered, self.bp_state = signal.sosfilt(self.bp, x, zi=self.bp_state)
        t = (np.arange(len(x)) + self.sample_index)/self.rate
        # Difference frequency: carrier - (carrier-tone) -> tone.
        mixed = filtered * (2*np.cos(2*np.pi*(self.carrier-self.tone)*t))
        audio, self.lp_state = signal.sosfilt(self.lp, mixed, zi=self.lp_state)
        envelope, self.env_state = signal.sosfilt(self.env_lp, filtered*filtered, zi=self.env_state)
        envelope = np.sqrt(np.maximum(envelope,0))*np.sqrt(2)
        self.sample_index += len(x)
        return raw, envelope, np.asarray(audio, dtype=np.float32)

def spectrum(data, rate=RATE):
    data = np.asarray(data, dtype=float)
    if len(data) < 256:
        return np.array([]), np.array([])
    win = np.hanning(len(data))
    fft = np.abs(np.fft.rfft(data * win)) / max(win.sum()/2, 1)
    db = 20*np.log10(np.maximum(fft, 1e-10))
    return np.fft.rfftfreq(len(data), 1/rate), db

MORSE = dict(zip(
    '.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --..'.split(),
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
MORSE.update(dict(zip('----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.'.split(),'0123456789')))
MORSE.update({'..--..':'?', '.-.-.-':'.', '--..--':',', '-..-.':'/', '-...-':'=', '.-.-.':'+', '-....-':'-', '.----.':"'"})

class MorseDecoder:
    """Envelope-based best effort decoder. Call feed with per-block envelope and block duration.

    Uses adaptive noise threshold, element duration, and 3/7-dot gaps.
    No character is emitted until a valid separating gap has elapsed.
    """
    def __init__(self, wpm=12, auto=True):
        self.wpm = wpm
        self.auto = auto
        self.reset()

    def reset(self):
        self.active = False
        self.elapsed = 0.0
        self.symbol = ''
        self.noise = 0.0
        self.peak = 0.0
        self.dot = 1.2 / max(1, self.wpm)
        self.last_space = False
        self.elements = []

    def settings(self, wpm, auto):
        self.wpm = wpm
        self.auto = auto
        if not auto: self.dot = 1.2/max(1,wpm)

    def feed(self, envelope, dt):
        e = np.asarray(envelope)
        if not len(e): return ''
        # Frame envelope smooth amplitude; noise estimate recovers on weak signals.
        level = float(np.percentile(e, 70))
        self.peak = max(level, self.peak * 0.995)
        self.noise = min(level, self.noise*0.995 + level*.005) if self.noise else level*.5
        threshold = max(self.peak * .33, 3e-6)
        on = level > threshold
        emitted = ''
        self.elapsed += dt
        if on != self.active:
            duration = self.elapsed
            self.elapsed = 0.0
            if self.active:
                if .25*self.dot < duration < 8*self.dot:
                    char = '-' if duration >= 2*self.dot else '.'
                    self.symbol += char
                    if self.auto:
                        estimate = duration/(3 if char=='-' else 1)
                        if .025 < estimate < .5:
                            self.dot = .85*self.dot + .15*estimate
                self.last_space = False
            else:
                if duration >= 2.4*self.dot and self.symbol:
                    emitted += MORSE.get(self.symbol,'?')
                    self.symbol = ''
                if duration >= 5.5*self.dot and not self.last_space:
                    emitted += ' '
                    self.last_space = True
            self.active = on
        elif not on:
            if self.symbol and self.elapsed >= 2.8*self.dot:
                emitted += MORSE.get(self.symbol, '?')
                self.symbol = ''
            if self.elapsed >= 7*self.dot and not self.last_space:
                emitted += ' '
                self.last_space = True
        return emitted
