import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import core
from core import transcribe, whisper_model


class AudioDecodeTests(unittest.TestCase):
    def test_cached_model_does_not_attempt_download(self):
        whisper_model.cache_clear()
        with patch("faster_whisper.WhisperModel") as loader:
            whisper_model("small", "cpu")
            self.assertEqual(loader.call_count, 1)
            self.assertTrue(loader.call_args.kwargs["local_files_only"])
        whisper_model.cache_clear()

    def test_missing_model_download_and_clear_failure_message(self):
        from huggingface_hub.errors import LocalEntryNotFoundError
        for success in (True, False):
            whisper_model.cache_clear()
            final = object() if success else LocalEntryNotFoundError("network blocked")
            with patch("faster_whisper.WhisperModel", side_effect=[LocalEntryNotFoundError("not cached"), final]) as loader:
                if success:
                    self.assertIs(whisper_model("small", "cpu"), final)
                else:
                    # The UI reload test recreates exception classes in core.
                    with self.assertRaisesRegex(core.ModelDownloadError, "first download"):
                        whisper_model("small", "cpu")
                self.assertEqual(loader.call_count, 2)
                self.assertNotIn("local_files_only", loader.call_args.kwargs)
        whisper_model.cache_clear()

    def write_wave(self, path, seconds):
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(b"\0\0" * 16000 * seconds)

    def test_decode_wave_and_preserve_word_times(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.wav"
            self.write_wave(path, 2)
            word = SimpleNamespace(start=0.1, end=0.8, word=" Hello")
            model = SimpleNamespace(transcribe=lambda audio, **kwargs: (
                iter([SimpleNamespace(words=[word])]), SimpleNamespace(language="en")))
            with patch("audio_idp.services.transcription.whisper_model", return_value=model):
                result = transcribe(path, "en", speakers=False)
            self.assertEqual(result["duration"], 2)
            self.assertEqual(result["segments"][0]["speaker"], "Unknown")
            self.assertEqual(result["segments"][0]["start"], 0.1)

    def test_reject_long_audio_before_loading_model(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "long.wav"
            self.write_wave(path, 601)
            with patch("audio_idp.services.transcription.whisper_model") as model:
                with self.assertRaisesRegex(ValueError, "10-minute"):
                    transcribe(path, "en", speakers=False)
                model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
