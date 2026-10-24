"""Safe dated session files under executable directory."""
import sys, json, wave, datetime
from pathlib import Path
import numpy as np

def base_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

def folders(root=None):
    root = Path(root) if root else base_dir()
    for name in ('config','recdata','masterdata'):
        (root/name).mkdir(parents=True, exist_ok=True)
    return root

def timestamp(now=None):
    now = now or datetime.datetime.now()
    return now.strftime('%Y%m%d-%H%M%S')

class Recorder:
    def __init__(self, root=None, rate=48000, now=None):
        root=folders(root)
        path=root/'recdata'/(timestamp(now)+'.wav')
        i=1
        while path.exists():
            path=root/'recdata'/(timestamp(now)+f'-{i}.wav'); i+=1
        self.path=path
        self.wav=wave.open(str(path),'wb')
        self.wav.setnchannels(1); self.wav.setsampwidth(2); self.wav.setframerate(rate)

    def write(self, data):
        if self.wav is not None:
            pcm=(np.clip(np.asarray(data),-1.0,0.999969)*32768).astype('<i2')
            self.wav.writeframes(pcm.tobytes())

    def close(self):
        if self.wav is not None:
            self.wav.close(); self.wav=None

class Transcript:
    def __init__(self, root=None):
        self.root=folders(root)
        self.lastday=None
    def append(self, text, now=None):
        if not text: return
        now=now or datetime.datetime.now()
        day=now.strftime('%Y%m%d')
        path=self.root/'masterdata'/f'{day}_ALL.txt'
        if day!=self.lastday:
            with path.open('a',encoding='utf-8') as f:
                f.write('\n['+now.strftime('%Y-%m-%d %H:%M:%S')+']\n')
            self.lastday=day
        with path.open('a',encoding='utf-8') as f:
            f.write(text)

def load_settings(root=None):
    path=folders(root)/'config'/'settings.json'
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}

def save_settings(settings,root=None):
    path=folders(root)/'config'/'settings.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)
