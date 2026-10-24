import sys
import argparse
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from pssaq.gui import MainWindow
from pssaq.updater import remove_legacy_backup
from pssaq.window_icon import application_icon,set_process_identity,install_taskbar_identity

def main():
    parser=argparse.ArgumentParser(description='PSSAQ 17.2 kHz receiver')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--self-test-icon',action='store_true')
    parser.add_argument('--report',help='JSON report path for the startup test')
    args=parser.parse_args()
    set_process_identity()
    app=QApplication(sys.argv)
    app.setApplicationName('PSSAQ')
    app.setWindowIcon(application_icon())
    if args.self_test_icon:
        from pssaq.selftest import run_icon
        return run_icon(app,args.report)
    if args.self_test:
        from pssaq.selftest import run
        return run(app,args.report)
    win=MainWindow()
    identity=install_taskbar_identity(win)
    win.show()
    if identity is not None:QTimer.singleShot(0,identity.apply)
    if sys.platform=='win32' and getattr(sys,'frozen',False):
        if not remove_legacy_backup(sys.executable):
            win.statusBar().showMessage(win.tr_text('旧EXEの.bakを削除できませんでした。ファイルが使用中でないか確認してください。'),10000)
    return app.exec()

if __name__=='__main__':
    raise SystemExit(main())
