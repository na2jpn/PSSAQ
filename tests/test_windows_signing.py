"""Exercise release signing commands without a certificate or Windows hardware."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.windows_signing import sign_executables, find_signtool
from scripts.package_release import package


class SigningTests(unittest.TestCase):
    def test_sign_then_verify_and_package_exact_signed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'PSSAQ.exe';exe.write_bytes(b'MZunsigned')
            archive=Path(tmp)/'pssaq_v0.94.zip'
            calls=[]
            def run(args,check):
                self.assertTrue(check);calls.append(args)
                if args[1]=='sign':exe.write_bytes(b'MZsigned-and-timestamped')
                elif args[1]=='verify':self.assertEqual(exe.read_bytes(),b'MZsigned-and-timestamped')
            with patch('scripts.windows_signing.find_signtool',return_value='signtool.exe'), \
                 patch('scripts.windows_signing.subprocess.run',side_effect=run):
                sign_executables([exe],'ab '*20,machine_store=True)
            self.assertEqual(calls[0][0:4],['signtool.exe','sign','/sha1','ab'*20])
            self.assertIn('/sm',calls[0])
            self.assertEqual(calls[0][calls[0].index('/tr')+1],'http://timestamp.digicert.com')
            self.assertEqual(calls[0][calls[0].index('/fd')+1],'SHA256')
            self.assertEqual(calls[0][calls[0].index('/td')+1],'SHA256')
            self.assertEqual(calls[1][1:6],['verify','/pa','/all','/tw','/v'])
            with patch('scripts.package_release.license_entries',return_value=[]):package(exe,archive)
            with ZipFile(archive) as z:
                self.assertEqual(z.read('PSSAQ.exe'),exe.read_bytes())
                self.assertIn('LICENSING.md',z.namelist())

    def test_automatic_certificate_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'PSSAQ.exe';exe.write_bytes(b'MZ')
            with patch('scripts.windows_signing.find_signtool',return_value='signtool.exe'), \
                 patch('scripts.windows_signing.subprocess.run') as run:
                sign_executables([exe],None)
            self.assertIn('/a',run.call_args_list[0].args[0])
            self.assertNotIn('/sha1',run.call_args_list[0].args[0])

    def test_signing_or_verification_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'PSSAQ.exe';exe.write_bytes(b'MZ')
            for effects,expected_calls in (([subprocess.CalledProcessError(1,'sign')],1),
                                            ([None,subprocess.CalledProcessError(2,'verify')],2)):
                with self.subTest(expected_calls=expected_calls), \
                     patch('scripts.windows_signing.find_signtool',return_value='signtool.exe'), \
                     patch('scripts.windows_signing.subprocess.run',side_effect=effects) as run:
                    with self.assertRaises(subprocess.CalledProcessError):sign_executables([exe],None)
                    self.assertEqual(run.call_count,expected_calls)

    def test_invalid_parameters_never_invoke_signtool(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'PSSAQ.exe';exe.write_bytes(b'MZ')
            with patch('scripts.windows_signing.subprocess.run') as run:
                for thumb,url in (('not-a-certificate','http://timestamp.digicert.com'),
                                  (None,'bad timestamp URL')):
                    with self.assertRaises(ValueError):sign_executables([exe],thumb,timestamp_url=url)
                with self.assertRaises(FileNotFoundError):sign_executables([Path(tmp)/'missing.exe'],None)
                with self.assertRaises(FileNotFoundError):find_signtool(Path(tmp)/'missing-tool.exe')
                run.assert_not_called()
