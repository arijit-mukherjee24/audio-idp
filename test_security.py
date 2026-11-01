"""Security-policy regressions using constructed, non-credential test values."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import security_check as security


class SecurityTests(unittest.TestCase):
    def test_private_paths_and_safe_example(self):
        for name in ('.env','.env.production','nested/.env.local','.aws/credentials',
                     '.streamlit/secrets.toml','.local/models/model.bin','.data/batches/result.json',
                     '.run/log.txt','recording.wav','exports/result.json','private.pem','x.sqlite3-wal'):
            self.assertTrue(security.private_path(name),name)
        for name in ('.env.example','.streamlit/config.toml','README.md','audio_idp/config.py',
                     '.github/workflows/ci.yml','.githooks/pre-commit'):
            self.assertFalse(security.private_path(name),name)

    def test_environment_values_detected_without_matching_non_secrets(self):
        value='unit-test-'+'not-a-real-credential'
        values=security.environment_secrets({'SERVICE_TOKEN':value,'NORMAL_SETTING':'value',
                                             'EXAMPLE_PASSWORD':'<placeholder>'})
        self.assertTrue(security.environment_match(('copied '+value).encode(),values))
        self.assertFalse(security.environment_match(b'ordinary source code',values))
        self.assertNotIn(b'<placeholder>',values)

    def test_staged_scan_reads_index_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['git','init','-q',folder],check=True)
            path=root/'source.py';path.write_text('staged content',encoding='utf-8')
            subprocess.run(['git','-C',folder,'add','source.py'],check=True)
            path.write_text('unstaged content',encoding='utf-8')
            def scan(tool,args,report,base=None):
                self.assertEqual((Path(args[1])/'source.py').read_text(),'staged content')
                return True
            with patch.object(security,'ROOT',root),patch.object(security,'install_tool',return_value=Path('unused')),patch.object(security,'scan',side_effect=scan):
                self.assertEqual(security.main(['--staged']),0)

    def test_force_added_env_is_blocked_before_scanner_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['git','init','-q',folder],check=True)
            (root/'.env').write_text('PRIVATE_SETTING=do-not-publish',encoding='utf-8')
            subprocess.run(['git','-C',folder,'add','-f','.env'],check=True)
            with patch.object(security,'ROOT',root),patch.object(security,'install_tool') as install:
                self.assertEqual(security.main(['--staged']),1)
                install.assert_not_called()

    def test_tampered_cached_scanner_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tools=root/'.run'/'tools';tools.mkdir(parents=True)
            (tools/f'gitleaks_{security.VERSION}_windows_x64.zip').write_bytes(b'tampered')
            with patch.object(security,'ROOT',root),patch.object(security.platform,'system',return_value='Windows'),patch.object(security.platform,'machine',return_value='AMD64'):
                with self.assertRaises(ValueError):security.install_tool(False)


if __name__=='__main__':unittest.main()
