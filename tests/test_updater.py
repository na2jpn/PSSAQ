import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile
from pssaq.updater import independent_environment,prepare_update,validate_archive,launch_update,remove_legacy_backup


class UpdateTests(unittest.TestCase):
    def test_restart_does_not_inherit_onefile_directory(self):
        original={'PATH':'system','SystemRoot':r'C:\Windows',
                  '_PYI_APPLICATION_HOME_DIR':r'C:\Temp\_MEI_deleted',
                  '_PYI_ARCHIVE_FILE':r'C:\Apps\PSSAQ.exe',
                  '_PYI_PARENT_PROCESS_LEVEL':'1','_PYI_SPLASH_IPC':'0',
                  '_MEIPASS2':'old','PYINSTALLER_RESET_ENVIRONMENT':'0'}
        result=independent_environment(original)
        self.assertEqual(result['PYINSTALLER_RESET_ENVIRONMENT'],'1')
        self.assertFalse(any(k.startswith('_PYI_') or k=='_MEIPASS2' for k in result))
        self.assertEqual(result['SystemRoot'],original['SystemRoot'])
        self.assertEqual(result['PATH'],'system')
        self.assertIn('_PYI_APPLICATION_HOME_DIR',original)

    def test_external_helper_library_path_restored(self):
        result=independent_environment({'LD_LIBRARY_PATH':'_MEI','LD_LIBRARY_PATH_ORIG':'user-libraries'})
        self.assertEqual(result['LD_LIBRARY_PATH'],'user-libraries')

    def test_stage_preserves_installed_exe_and_all_user_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"日本語 space % & $'"
            root.mkdir()
            target=root/'RenamedPSSAQ.exe';target.write_bytes(b'MZ old')
            for name in ('config','recdata','masterdata','language'):
                (root/name).mkdir();(root/name/'keep.txt').write_text('keep',encoding='utf-8')
            archive=root/'new.zip'
            with ZipFile(archive,'w') as z:z.writestr('PSSAQ.exe',b'MZ new complete')
            manifest=prepare_update(archive,target,123)
            job=json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual(job['target'],str(target.resolve()))
            self.assertEqual(job['process_id'],123)
            self.assertNotIn('backup',job)
            self.assertFalse(list(root.glob('*.bak')))
            self.assertEqual(job['sha256'],hashlib.sha256(b'MZ new complete').hexdigest())
            self.assertEqual(Path(job['incoming']).read_bytes(),b'MZ new complete')
            self.assertEqual(target.read_bytes(),b'MZ old')
            self.assertTrue((manifest.parent/'apply_update.ps1').is_file())
            for name in ('config','recdata','masterdata','language'):
                self.assertEqual((root/name/'keep.txt').read_text(encoding='utf-8'),'keep')

    def test_repeated_attempts_have_separate_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'PSSAQ.exe';target.write_bytes(b'MZ old')
            archive=root/'new.zip'
            with ZipFile(archive,'w') as z:z.writestr('PSSAQ.exe',b'MZ new')
            a=prepare_update(archive,target);b=prepare_update(archive,target)
            self.assertNotEqual(a,b);self.assertTrue(a.is_file());self.assertTrue(b.is_file())

    def test_bad_paths_are_rejected(self):
        for name in ('../evil','a/../../evil','..\\evil','/absolute','C:/evil','a/file:stream','\\\\server\\file'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                archive=Path(tmp)/'test.zip'
                with ZipFile(archive,'w') as z:
                    z.writestr('PSSAQ.exe',b'MZ new');z.writestr(name,b'bad')
                with ZipFile(archive) as z,self.assertRaises(ValueError):validate_archive(z)

    def test_duplicate_missing_and_onedir_exe_are_rejected(self):
        for names in (['source.py'],['PSSAQ.exe','folder/PSSAQ.exe'],['PSSAQ.exe','_internal/python312.dll']):
            with self.subTest(names=names),tempfile.TemporaryDirectory() as tmp:
                archive=Path(tmp)/'test.zip'
                with ZipFile(archive,'w') as z:
                    for name in names:z.writestr(name,b'MZ data')
                with ZipFile(archive) as z,self.assertRaises(ValueError):validate_archive(z)

    def test_non_windows_exe_does_not_create_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'PSSAQ.exe';target.write_bytes(b'MZ old')
            archive=root/'test.zip'
            with ZipFile(archive,'w') as z:z.writestr('PSSAQ.exe',b'not an exe')
            with self.assertRaises(ValueError):prepare_update(archive,target)
            self.assertFalse(list(root.glob('update-*')))
            self.assertEqual(target.read_bytes(),b'MZ old')

    def test_launcher_uses_clean_environment_and_argument_list(self):
        with patch.dict(os.environ,{'_PYI_APPLICATION_HOME_DIR':'deleted'},clear=False), \
             patch('pssaq.updater.subprocess.Popen') as popen:
            manifest=Path("path with space $ & '/update.json").resolve()
            launch_update(manifest)
            args=popen.call_args.args[0]
            self.assertEqual(args[-2:],['-Manifest',str(manifest)])
            self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'],'1')
            self.assertNotIn('_PYI_APPLICATION_HOME_DIR',popen.call_args.kwargs['env'])
            self.assertFalse(popen.call_args.kwargs.get('shell',False))
            self.assertEqual(popen.call_args.kwargs['cwd'],str(manifest.parent.parent))

    def test_migration_removes_only_own_legacy_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/'Renamed PSSAQ.exe';target.write_bytes(b'MZ new')
            backup=root/'Renamed PSSAQ.exe.bak';backup.write_bytes(b'MZ old')
            unrelated=root/'another.exe.bak';unrelated.write_bytes(b'keep')
            self.assertTrue(remove_legacy_backup(target))
            self.assertFalse(backup.exists())
            self.assertEqual(target.read_bytes(),b'MZ new')
            self.assertEqual(unrelated.read_bytes(),b'keep')
            self.assertTrue(remove_legacy_backup(target))

    def test_locked_legacy_backup_reports_failure_without_touching_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'PSSAQ.exe';target.write_bytes(b'MZ new')
            with patch.object(Path,'unlink',side_effect=PermissionError('locked')):
                self.assertFalse(remove_legacy_backup(target))
            self.assertEqual(target.read_bytes(),b'MZ new')
