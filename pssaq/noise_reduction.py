"""Small streaming spectral noise reducer for the listening path only."""
import numpy as np
from scipy.ndimage import median_filter


class MonitorNoiseReducer:
    """Soft spectral subtraction with a local median noise estimate.

    Narrow spectral peaks are retained while broadband bins are attenuated.
    It cannot distinguish interference at the exact CW pitch from the signal.
    A square-root Hann analysis/synthesis pair and overlap normalization keep
    arbitrary input block sizes continuous. Enabled latency is 1536 samples.
    """
    size = 1536
    hop = 384
    latency = size

    def __init__(self, level=0):
        self.level = -1
        self.set_level(level)

    def set_level(self, level):
        level = int(np.clip(level, 0, 3))
        if level == self.level:
            return
        self.level = level
        self.reset()

    def reset(self):
        self.window = np.sqrt(np.hanning(self.size + 1)[:-1])
        self.pending = np.zeros(self.size - self.hop)
        self.ready = np.zeros(self.hop)
        self.overlap = np.zeros(self.size)
        self.weight = np.zeros(self.size)
        self.power = None
        self.gain = np.ones(self.size // 2 + 1)

    def process(self, block):
        x = np.asarray(block, dtype=np.float32).reshape(-1)
        if not self.level or not len(x):
            return x.copy()
        self.pending = np.concatenate((self.pending, x))
        output = []
        while len(self.pending) >= self.size:
            frame = self.pending[:self.size] * self.window
            self.pending = self.pending[self.hop:]
            bins = np.fft.rfft(frame)
            power = np.abs(bins) ** 2
            self.power = power if self.power is None else .65 * self.power + .35 * power
            # A CW peak spans fewer bins than this median window. Unlike a
            # long-term minimum tracker, this does not learn a steady carrier
            # as noise and then erase it.
            noise = 1.25 * median_filter(self.power, size=7, mode='nearest')
            amount, floor = ((.8, .55), (1.4, .35), (2.2, .18))[self.level - 1]
            target = np.sqrt(np.maximum(1 - amount * noise / (self.power + 1e-20), floor ** 2))
            # Let peaks open quickly; close more slowly to reduce chattering.
            speed = np.where(target > self.gain, .7, .2)
            self.gain += speed * (target - self.gain)
            clean = np.fft.irfft(bins * self.gain, n=self.size) * self.window
            self.overlap += clean
            self.weight += self.window ** 2
            output.append(self.overlap[:self.hop] / np.maximum(self.weight[:self.hop], 1e-12))
            self.overlap[:-self.hop] = self.overlap[self.hop:]
            self.overlap[-self.hop:] = 0
            self.weight[:-self.hop] = self.weight[self.hop:]
            self.weight[-self.hop:] = 0
        self.ready = np.concatenate((self.ready, *output))
        result = self.ready[:len(x)].astype(np.float32)
        self.ready = self.ready[len(x):]
        return result
