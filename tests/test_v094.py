import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6 import QtWidgets
from pssaq.gui import MainWindow
from pssaq.history import RELEASES


class Help094Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_help_menu_opens_separate_license_and_history_in_all_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(tmp,auto_start=False);window.timer.stop()
            try:
                for lang in ('ja','en','ru'):
                    window.change_language(lang)
                    actions=[a for a in window.help_menu.actions() if not a.isSeparator()]
                    self.assertEqual([a.text() for a in actions],
                                     [window.tr_text(k) for k in ('バージョンアップ（ZIP指定）','ライセンス','更新履歴','PSSAQについて')])
                    def inspect(dialog):
                        if dialog.windowTitle()==window.tr_text('ライセンス')+' — PSSAQ':
                            tabs=dialog.findChild(QtWidgets.QTabWidget)
                            self.assertEqual(tabs.count(),3)
                            self.assertEqual(tabs.tabText(2),window.tr_text('第三者ライブラリ'))
                            self.assertIn('GNU GENERAL PUBLIC LICENSE',tabs.widget(0).toPlainText())
                        else:
                            self.assertEqual(dialog.windowTitle(),window.tr_text('更新履歴')+' — PSSAQ')
                            body=dialog.findChild(QtWidgets.QTextBrowser).toPlainText()
                            self.assertIn('v0.94 (2026-11-25)',body)
                            self.assertIn(window.tr_text(RELEASES[0][2][0]),body)
                            self.assertNotIn('windows.ps1',body)
                        return 0
                    with patch.object(QtWidgets.QDialog,'exec',inspect):
                        actions[1].trigger();actions[2].trigger()
                    self.assertIsNone(window.input_stream)
            finally:window.close()

    def test_bundled_license_resources_beat_stale_external_files(self):
        from pssaq.resources import license_path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'licenses').mkdir()
            (root/'LICENSE.md').write_text('current GPL',encoding='utf-8')
            (root/'LICENSING.md').write_text('current guide',encoding='utf-8')
            (root/'licenses/NOTICE.txt').write_text('third parties',encoding='utf-8')
            with patch('pssaq.resources.sys._MEIPASS',str(root),create=True):
                self.assertEqual(license_path().read_text(encoding='utf-8'),'current GPL')
                self.assertEqual(license_path('licenses/NOTICE.txt').read_text(encoding='utf-8'),'third parties')
