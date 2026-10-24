# One-file Windows build, also usable on Linux for packaging regression tests.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH)
# SciPy loads array_api_compat backends through importlib. Collect the complete
# namespace (including _external on newer SciPy and _lib on older SciPy).
# Ordinary static import analysis misses numpy.fft in these private packages.
scipy_data, scipy_bins, scipy_hidden = collect_all(
    'scipy', include_py_files=False,
    filter_submodules=lambda name: not {'tests', 'testing'}.intersection(name.split('.')),
    exclude_datas=['**/tests/**', '**/testing/**'])
datas = scipy_data + [(str(root / 'assets'), 'assets'), (str(root / 'language'), 'language'),
                      (str(root / 'LICENSE.md'), '.')]
for package in ('numpy', 'scipy', 'PySide6', 'sounddevice'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'main.py')], pathex=[str(root)],
             binaries=scipy_bins, datas=datas, hiddenimports=scipy_hidden,
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['tkinter', 'matplotlib', 'IPython'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PSSAQ',
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=False, icon=str(root / 'assets' / 'pssaq.ico'),
          version=str(root / 'assets' / 'version_info.txt'))
