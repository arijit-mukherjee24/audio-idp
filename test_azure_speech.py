import io
import json
import os
import unittest
import wave
from unittest.mock import Mock, patch

import numpy as np
import requests

from audio_idp.providers import azure_speech as azure
from audio_idp.services.transcription import transcribe
from audio_idp.workflow.job_manager import safe_error


DOCUMENT = {'durationMilliseconds': 1000, 'phrases': [
    {'offsetMilliseconds': 100, 'durationMilliseconds': 800, 'text': 'Hello, world!', 'locale': 'en-US',
     'words': [{'text': 'Hello,', 'offsetMilliseconds': 100, 'durationMilliseconds': 300},
               {'text': 'world!', 'offsetMilliseconds': 500, 'durationMilliseconds': 400}]}]}


class AzureSpeechTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {'AZURE_SPEECH_ENDPOINT': 'https://example.cognitiveservices.azure.com/',
                                                   'AZURE_SPEECH_KEY': 'synthetic-test-value', 'AZURE_SPEECH_AUTH': 'key'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.response = Mock(status_code=200)
        self.response.json.return_value = DOCUMENT
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.post = patch.object(azure.requests, 'post', return_value=self.response).start()
        self.addCleanup(patch.stopall)
        self.audio = np.zeros(16000, dtype=np.float32)

    def test_direct_upload_with_language_and_no_blob_storage(self):
        document, metadata = azure.transcribe_audio(self.audio, 'en')
        call = self.post.call_args
        self.assertEqual(call.args[0], 'https://example.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe')
        self.assertEqual(call.kwargs['params'], {'api-version': '2025-10-15'})
        self.assertEqual(call.kwargs['headers'], {'Ocp-Apim-Subscription-Key': 'synthetic-test-value'})
        self.assertFalse(call.kwargs['allow_redirects'])
        definition = json.loads(call.kwargs['files']['definition'][1])
        self.assertEqual(definition['locales'], ['en-US'])
        self.assertFalse(definition['diarization']['enabled'])
        with wave.open(io.BytesIO(call.kwargs['files']['audio'][1]), 'rb') as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (1, 16000, 16000))
        self.assertEqual(metadata['provider'], 'azure')
        self.assertEqual(metadata['language_code'], 'en-US')
        self.assertEqual(document, DOCUMENT)

    def test_auto_detection_restricts_locales_to_supported_app_languages(self):
        azure.transcribe_audio(self.audio, None)
        definition = json.loads(self.post.call_args.kwargs['files']['definition'][1])
        self.assertEqual(definition['locales'], ['en-US', 'es-ES', 'fr-FR'])

    def test_service_preserves_word_times_and_punctuation_without_whisper(self):
        with patch('audio_idp.services.audio_validation.decode_audio', return_value=self.audio):
            with patch('audio_idp.services.transcription.whisper_model') as whisper:
                result = transcribe('unused.wav', None, provider='azure')
        whisper.assert_not_called()
        self.assertEqual(result['language'], 'en')
        self.assertEqual(result['duration'], 1)
        self.assertEqual(result['text'], '[0.10-0.90] Unknown: Hello, world!')
        self.assertEqual(result['provider'], 'azure')

    def test_phrase_timing_is_used_if_word_times_are_absent(self):
        document = {'phrases': [{'offsetMilliseconds': 1000, 'durationMilliseconds': 2000, 'text': 'Hello there.'}]}
        self.assertEqual(azure.words_from_result(document), [{'start': 1, 'end': 3, 'text': ' Hello there.'}])

    def test_missing_configuration_rejected_before_network_request(self):
        for setting in ('AZURE_SPEECH_ENDPOINT', 'AZURE_SPEECH_KEY'):
            with self.subTest(setting=setting), patch.dict(os.environ, {setting: ''}):
                with self.assertRaisesRegex(azure.AzureTranscriptionError, setting):
                    azure.transcribe_audio(self.audio, 'en')
        self.post.assert_not_called()

    def test_insecure_or_nonbase_endpoint_is_rejected(self):
        for endpoint in ('http://example.com', 'https://user:secret@example.com',
                         'https://example.com/path', 'https://example.com?key=secret'):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {'AZURE_SPEECH_ENDPOINT': endpoint}):
                with self.assertRaises(azure.AzureTranscriptionError):
                    azure.transcribe_audio(self.audio, 'en')
        self.post.assert_not_called()

    def test_status_errors_are_actionable_and_do_not_echo_response_body(self):
        for status in (400, 401, 403, 404, 429, 500):
            self.response.status_code = status
            self.response.text = 'private content synthetic-test-value'
            with self.subTest(status=status), self.assertRaisesRegex(azure.AzureTranscriptionError, f'HTTP {status}') as error:
                azure.transcribe_audio(self.audio, 'en')
            self.assertNotIn('private content', safe_error(error.exception))
            self.assertNotIn('synthetic-test-value', safe_error(error.exception))

    def test_timeout_does_not_resubmit_a_paid_request(self):
        self.post.side_effect = requests.Timeout('private endpoint details')
        with self.assertRaisesRegex(azure.AzureTranscriptionError, 'another charge'):
            azure.transcribe_audio(self.audio, 'en')
        self.post.assert_called_once()

    def test_network_error_has_a_safe_message(self):
        self.post.side_effect = requests.ConnectionError('private configuration')
        with self.assertRaisesRegex(azure.AzureTranscriptionError, 'Cannot reach Azure Speech'):
            azure.transcribe_audio(self.audio, 'en')

    def test_invalid_json_or_missing_phrases_is_rejected(self):
        self.response.json.side_effect = ValueError('invalid')
        with self.assertRaisesRegex(azure.AzureTranscriptionError, 'invalid JSON'):
            azure.transcribe_audio(self.audio, 'en')
        self.response.json.side_effect = None
        self.response.json.return_value = {'combinedPhrases': []}
        with self.assertRaisesRegex(azure.AzureTranscriptionError, 'without timestamped phrases'):
            azure.transcribe_audio(self.audio, 'en')

    def test_no_speech_is_rejected(self):
        self.response.json.return_value = {'phrases': []}
        with patch('audio_idp.services.audio_validation.decode_audio', return_value=self.audio):
            with self.assertRaisesRegex(ValueError, 'No speech detected'):
                transcribe('unused.wav', None, provider='azure')

    def test_unknown_auth_mode_is_rejected(self):
        with patch.dict(os.environ, {'AZURE_SPEECH_AUTH': 'other'}):
            with self.assertRaisesRegex(azure.AzureTranscriptionError, 'must be key or entra'):
                azure.transcribe_audio(self.audio, 'en')
        self.post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
