import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch
from PySide6 import QtCore, QtGui, QtWidgets
from pssaq.i18n import Language, LANGUAGES, bundled_language_dir, read_catalog
from pssaq.gui import MainWindow, SettingsDialog
from pssaq.storage import load_settings
from pssaq.resources import license_path
from pssaq.updater import validate_archive
from scripts.package_release import package
from zipfile import ZipFile


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_all_shipped_catalogues_complete_with_matching_placeholders(self):
        catalogues = {code: read_catalog(bundled_language_dir() / f'{code}.json') for code in LANGUAGES}
        fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name is not None}
        for code, strings in catalogues.items():
            self.assertEqual(set(strings), set(catalogues['ja']))
            for key, value in strings.items():
                self.assertEqual(fields(key), fields(value), (code, key))
                self.assertTrue(value)
        with tempfile.TemporaryDirectory() as tmp:
            lang = Language(tmp, 'ru')
            self.assertEqual(lang.text('入力 {db:.1f} dBFS', db=-32.8), 'Вход -32.8 dBFS')

    def test_exe_only_update_creates_external_files_and_preserves_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lang = Language(root)
            self.assertEqual({p.name for p in (root / 'language').iterdir()}, {'ja.json', 'en.json', 'ru.json'})
            custom = root / 'language' / 'en.json'
            custom.write_text(json.dumps({'strings': {'出力テスト': 'Custom OUT'}}), encoding='utf-8')
            lang = Language(root, 'en')
            self.assertEqual(lang.text('出力テスト'), 'Custom OUT')
            self.assertEqual(lang.text('設定'), 'Settings')
            self.assertEqual(json.loads(custom.read_text(encoding='utf-8'))['strings']['出力テスト'], 'Custom OUT')

    def test_invalid_external_files_fall_back_to_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Language(root)
            path = root / 'language' / 'ru.json'
            for content in (b'not json', b'\xff', b'{"strings": []}',
                            json.dumps({'strings': {'入力 {db:.1f} dBFS': '{wrong}'}}).encode('utf-8')):
                path.write_bytes(content)
                self.assertEqual(Language(root, 'ru').text('出力テスト'), 'Тест OUT')
            self.assertEqual(Language(root, '../../unknown').code, 'ja')

    def test_read_only_external_directory_uses_bundled_languages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'language').write_bytes(b'cannot create directory here')
            self.assertEqual(Language(root, 'en').text('設定'), 'Settings')

    def test_release_zip_contains_languages_and_remains_update_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'PSSAQ.exe'
            exe.write_bytes(b'MZ test executable')
            archive = root / 'pssaq_v0.93.zip'
            with patch('scripts.package_release.license_entries', return_value=[]):
                package(exe, archive)
            with ZipFile(archive) as z:
                self.assertEqual(validate_archive(z).filename, 'PSSAQ.exe')
                self.assertEqual(z.read('LICENSE.md'),Path('LICENSE.md').read_bytes())
                for code in LANGUAGES:
                    data = json.loads(z.read(f'language/{code}.json').decode('utf-8'))
                    self.assertEqual(data['code'], code)
                    self.assertIn('出力テスト', data['strings'])

    def test_live_switch_preserves_recording_data_and_saves_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(tmp, auto_start=False)
            window.timer.stop()
            try:
                window.decoded.setPlainText('VVV DE SAQ')
                window.toggle_record()
                recorder = window.recorder
                window.gain.setValue(147)
                window.speed.setValue(23)
                window.volume.setValue(73)
                window.preview_timer.stop()
                window.set_status('RX / audio overrun {count}', count=3)
                window._last_db = -32.8
                for code, label, menu in (('en', 'Test OUT', 'File'), ('ru', 'Тест OUT', 'Файл'), ('ja', '出力テスト', 'ファイル')):
                    window.language_actions[code].trigger()
                    self.assertEqual(window.output_test.text(), label)
                    self.assertEqual(window.menuBar().actions()[0].text(), menu)
                    self.assertIs(window.recorder, recorder)
                    self.assertEqual(window.rec.text(), '■ STOP')
                    self.assertEqual(window.gain.value(), 147)
                    self.assertEqual(window.gaintext.text(), '147%')
                    self.assertEqual(window.speedtext.text(), '23 WPM')
                    self.assertEqual(window.volume_text.text(), '73%')
                    self.assertEqual(window.decoded.toPlainText(), 'VVV DE SAQ')
                    self.assertIn('3', window.status.text())
                    self.assertIn('-32.8', window.level.text())
                window.change_language('ru')
                self.assertEqual(load_settings(tmp)['language'], 'ru')
            finally:
                window.close()
            restored = MainWindow(tmp, auto_start=False)
            try:
                self.assertEqual(restored.output_test.text(), 'Тест OUT')
                self.assertTrue(restored.language_actions['ru'].isChecked())
                self.assertEqual(restored.rec.text(), '● REC')
            finally:
                restored.close()

    def test_settings_and_about_follow_selected_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(tmp, auto_start=False)
            window.timer.stop()
            try:
                for code, channel, heading, attribution in (
                    ('en', '1 (Mono / Left)', 'About PSSAQ', 'photograph published by ARRL'),
                    ('ru', '1 (Моно / Левый)', 'О PSSAQ', 'опубликованной ARRL'),
                    ('ja', '1 (モノラル/左)', 'PSSAQについて', 'ARRLの掲載の写真をイラストにしたものです。')):
                    window.change_language(code)
                    with patch('pssaq.gui.sd', None):
                        dialog = SettingsDialog(window.cfg, window)
                    self.assertEqual(dialog.channel.itemText(0), channel)
                    dialog.deleteLater()
                    def inspect(dialog):
                        if dialog.windowTitle()=='PS Ham-ware / AKIHABARA-GIKEN License':
                            expected=QtGui.QTextDocument()
                            expected.setMarkdown(license_path().read_text(encoding='utf-8-sig'))
                            self.assertEqual(dialog.findChild(QtWidgets.QTextBrowser).toPlainText(),expected.toPlainText())
                            self.assertEqual(dialog.parent().windowTitle(),heading)
                            return 0
                        self.assertEqual(dialog.windowTitle(), heading)
                        body = dialog.findChild(QtWidgets.QTextBrowser).toPlainText()
                        doc = dialog.findChild(QtWidgets.QTextBrowser).document()
                        icon = doc.resource(QtGui.QTextDocument.ImageResource, QtCore.QUrl('pssaq-icon'))
                        self.assertIsInstance(icon, QtGui.QImage)
                        self.assertFalse(icon.isNull())
                        self.assertIn('pssaq-icon', doc.toHtml().split('<h2')[0])
                        self.assertIn(attribution, body)
                        self.assertIn('Copyright © 2026 H. Tanaka (JH1HST)', body)
                        self.assertIn('PS Ham-ware / AKIHABARA-GIKEN',body)
                        button=next(b for b in dialog.findChildren(QtWidgets.QPushButton)
                                    if b.text()==window.tr_text('共通ライセンス全文'))
                        button.click()
                        return 0
                    with patch.object(QtWidgets.QDialog, 'exec', inspect):
                        window.about()
            finally:
                window.close()
