"""Short output check sound, played by the normal Audio OUT callback."""
import numpy as np
from .dsp import RATE


def output_chime(rate=RATE):
    notes = []
    for hz, duration in ((880, .09), (1320, .15)):
        count = round(rate * duration)
        t = np.arange(count) / rate
        fade = min(round(rate * .008), count // 2)
        envelope = np.ones(count)
        ramp = np.sin(np.linspace(0, np.pi / 2, fade)) ** 2
        envelope[:fade] = ramp
        envelope[-fade:] = ramp[::-1]
        notes.append(.22 * np.sin(2 * np.pi * hz * t) * envelope)
    return np.concatenate(notes).astype(np.float32)
