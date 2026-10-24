"""UTF-8 language catalogues, external beside the EXE and bundled as fallback."""
import json
from pathlib import Path
import sys
from .storage import base_dir

LANGUAGES = {'ja': '日本語', 'en': 'English', 'ru': 'Русский'}


def bundled_language_dir():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'language'


def read_catalog(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    strings = data['strings']
    if not isinstance(strings, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in strings.items()):
        raise ValueError('Invalid language catalogue')
    # Bad placeholders must never break live reception.
    from string import Formatter
    fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name is not None}
    if any(fields(k) != fields(v) for k, v in strings.items()):
        raise ValueError('Language placeholders do not match')
    return strings


class Language:
    def __init__(self, root=None, code='ja'):
        self.root = Path(root) if root is not None else base_dir()
        self.catalogues = {}
        bundle = bundled_language_dir()
        external = self.root / 'language'
        for lang in LANGUAGES:
            source = bundle / f'{lang}.json'
            # EXE-only updates (including v0.6 -> v0.7) install missing files.
            # Existing user-edited translations are preserved.
            try:
                external.mkdir(parents=True, exist_ok=True)
                with (external / source.name).open('x', encoding='utf-8') as f:
                    f.write(source.read_text(encoding='utf-8'))
            except (OSError, UnicodeError):
                pass
            strings = read_catalog(source)
            try:
                strings.update(read_catalog(external / source.name))
            except (OSError, ValueError, KeyError, TypeError):
                pass
            self.catalogues[lang] = strings
        self.select(code)

    def select(self, code):
        self.code = code if code in LANGUAGES else 'ja'

    def text(self, source, **values):
        text = self.catalogues[self.code].get(source, source)
        return text.format(**values) if values else text
