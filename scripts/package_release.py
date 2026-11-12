"""Create update-compatible PSSAQ distribution with bundled dependency notices.

Library licences are harvested from the *installed build environment*, not fabricated.
Legal compliance (notably LGPL Qt) must still be checked before public distribution.
"""
from __future__ import annotations
import argparse
from importlib import metadata
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

PACKAGES = ('PySide6', 'PySide6-Addons', 'PySide6-Essentials', 'shiboken6',
            'numpy', 'scipy', 'sounddevice', 'pyinstaller')


def license_entries():
    yield ('LICENSES/NOTICE.txt', Path('licenses/NOTICE.txt').read_bytes())
    for name in PACKAGES:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        files = dist.files or []
        for item in files:
            file_path = str(item).replace('\\', '/')
            basename = Path(file_path).name.lower()
            if not (basename.startswith(('license', 'copying', 'notice')) or basename == 'authors'):
                continue
            if not ('.dist-info/' in file_path or '.data/' in file_path):
                continue
            located = Path(dist.locate_file(item))
            if located.is_file() and located.stat().st_size <= 4_000_000:
                target = f'LICENSES/{name}/{Path(file_path).name}'
                yield (target, located.read_bytes())


def package(exe: Path, output: Path):
    if not exe.is_file():
        raise FileNotFoundError(exe)
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as z:
        z.write(exe, 'PSSAQ.exe')
        z.write('LICENSE.md', 'LICENSE.md')
        z.write('LICENSING.md', 'LICENSING.md')
        for path in sorted(Path('language').glob('*.json')):
            z.write(path, 'language/' + path.name)
        seen = set()
        for name, content in license_entries():
            if name not in seen:
                z.writestr(name, content)
                seen.add(name)
        z.writestr('LICENSES/READ_ME_FIRST.txt',
                   'This archive includes licence materials identified in the build environment.\n'
                   'Check Python/Qt/PySide6 licence requirements and LGPL compliance\n'
                   'before public redistribution. Not a guarantee of compliance.\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    if a.output.name != f'pssaq_v{a.version}.zip':
        parser.error('Output filename does not match version')
    package(a.exe, a.output)
