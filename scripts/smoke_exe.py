"""Run the built executable. An import failure must fail the build, too."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def check(executable):
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix='pssaq-exe-check-') as tmp:
        report = Path(tmp) / 'startup.json'
        env = os.environ.copy()
        env['QT_QPA_PLATFORM'] = 'offscreen'
        try:
            result = subprocess.run([str(executable), '--self-test', '--report', str(report)],
                                    cwd=tmp, env=env, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('EXE startup test timed out after 120 seconds') from exc
        if not report.is_file():
            raise RuntimeError(f'EXE did not finish startup (exit {result.returncode}); '
                               'check the EXE error dialog and PyInstaller build log')
        content = json.loads(report.read_text(encoding='utf-8'))
        if result.returncode != 0 or not content.get('ok'):
            raise RuntimeError(f'EXE startup test failed: {content}')
        print(f"EXE startup OK: PSSAQ {content['version']}; " + ', '.join(content['checks']))
        if os.name=='nt':
            # The normal DSP check is offscreen. Taskbar properties require a
            # real Windows HWND, so check those in a second isolated process.
            native_env=env.copy();native_env.pop('QT_QPA_PLATFORM',None)
            native_report=Path(tmp)/'native-icon.json'
            native=subprocess.run([str(executable),'--self-test-icon','--report',str(native_report)],
                                  cwd=tmp,env=native_env,timeout=60,check=False)
            if not native_report.is_file():raise RuntimeError('Windows icon check did not produce a report')
            icons=json.loads(native_report.read_text(encoding='utf-8'))
            if native.returncode!=0 or not icons.get('ok'):raise RuntimeError(f'Windows icon check failed: {icons}')
            print('Windows taskbar icon OK: '+', '.join(icons['checks']))
        return content


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('executable')
    check(parser.parse_args().executable)
