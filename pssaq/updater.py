"""Prepare an update without touching the running executable or user data."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile
from .resources import asset_path


def independent_environment(source=None):
    env=dict(os.environ if source is None else source)
    for key in list(env):
        if key.upper().startswith('_PYI_') or key.upper()=='_MEIPASS2':
            del env[key]
    env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    # Launching a system helper on POSIX must not reuse bundled libraries.
    for key in ('LD_LIBRARY_PATH','LIBPATH'):
        if key+'_ORIG' in env:env[key]=env[key+'_ORIG']
    return env


def validate_archive(archive):
    exes=[]
    for item in archive.infolist():
        path=PurePosixPath(item.filename.replace('\\','/'))
        if path.is_absolute() or '..' in path.parts or any(':' in part for part in path.parts):
            raise ValueError('安全でないZIP内のパスを検出しました。')
        if '_internal' in (part.lower() for part in path.parts):
            raise ValueError('フォルダー形式のEXEには対応していません。正式な1ファイル版ZIPを選んでください。')
        if path.name.lower()=='pssaq.exe' and not item.is_dir():exes.append(item)
    if len(exes)!=1:
        raise ValueError('PSSAQ.exeが1つだけ含まれる配布ZIPを選んでください。')
    return exes[0]


def prepare_update(zip_path, executable, process_id=None):
    target=Path(executable).resolve()
    if not target.is_file():raise FileNotFoundError(target)
    with zipfile.ZipFile(zip_path) as archive:
        member=validate_archive(archive)
        with archive.open(member) as src:
            if src.read(2)!=b'MZ':raise ValueError('Windows EXE形式ではありません。')
        # Separate staging folders preserve any earlier failed update evidence.
        stage=Path(tempfile.mkdtemp(prefix='update-',dir=target.parent))
        try:
            incoming=stage/'PSSAQ.exe'
            with archive.open(member) as src,incoming.open('wb') as dst:
                shutil.copyfileobj(src,dst)
            digest=hashlib.sha256(incoming.read_bytes()).hexdigest()
            script=stage/'apply_update.ps1'
            shutil.copyfile(asset_path('apply_update.ps1'),script)
            job={'target':str(target),'incoming':str(incoming),'sha256':digest,
                 'process_id':os.getpid() if process_id is None else int(process_id)}
            manifest=stage/'update.json'
            manifest.write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
            return manifest
        except Exception:
            shutil.rmtree(stage,ignore_errors=True)
            raise


def launch_update(manifest):
    manifest=Path(manifest).resolve()
    powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    args=[str(powershell),'-NoProfile','-ExecutionPolicy','Bypass','-File',
          str(manifest.parent/'apply_update.ps1'),'-Manifest',str(manifest)]
    # SetDllDirectory is inherited independently of os.environ on Windows.
    dll_path=None
    if sys.platform=='win32' and getattr(sys,'frozen',False):
        dll_path=getattr(sys,'_MEIPASS',None)
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        return subprocess.Popen(args,cwd=str(manifest.parent.parent),
                                env=independent_environment(),
                                creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
    finally:
        if dll_path is not None:ctypes.windll.kernel32.SetDllDirectoryW(str(dll_path))


def remove_legacy_backup(executable):
    """Remove only this executable's old updater backup, never other .bak files.

    Call on normal installed-app startup, after the older updater has launched
    the new EXE. Self-tests run before installation and must never do this.
    """
    backup=Path(str(Path(executable).resolve())+'.bak')
    try:
        backup.unlink(missing_ok=True)
        return True
    except OSError:
        return False
