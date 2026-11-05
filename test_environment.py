import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audio_idp.environment import load_environment


class EnvironmentTests(unittest.TestCase):
    def test_env_file_loads_without_overwriting_shell_or_expanding_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.env'
            path.write_text('AUDIO_IDP_DOTENV_PROBE=file\nAUDIO_IDP_LITERAL_PROBE=${AUDIO_IDP_DOTENV_PROBE}\n',encoding='utf-8-sig')
            with patch.dict(os.environ,{'AUDIO_IDP_DOTENV_PROBE':'shell'}):
                os.environ.pop('AUDIO_IDP_LITERAL_PROBE',None)
                load_environment(path)
                self.assertEqual(os.environ['AUDIO_IDP_DOTENV_PROBE'],'shell')
                self.assertEqual(os.environ['AUDIO_IDP_LITERAL_PROBE'],'${AUDIO_IDP_DOTENV_PROBE}')

    def test_missing_env_file_is_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(load_environment(Path(folder)/'missing.env'))
