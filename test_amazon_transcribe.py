import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from botocore.exceptions import ClientError

from audio_idp.providers import amazon_transcribe as aws
from audio_idp.persistence.database import Store
from audio_idp.services.transcription import transcribe
from audio_idp.workflow.coordinator import Workspace
from audio_idp.workflow.job_manager import safe_error


def error(code, message='test error'):
    return ClientError({'Error': {'Code': code, 'Message': message}}, 'GetTranscriptionJob')


DOCUMENT = {'results': {'items': [
    {'type': 'pronunciation', 'start_time': '0.1', 'end_time': '0.4', 'alternatives': [{'content': 'Hello'}]},
    {'type': 'punctuation', 'alternatives': [{'content': ','}]},
    {'type': 'pronunciation', 'start_time': '0.5', 'end_time': '0.9', 'alternatives': [{'content': 'world'}]},
    {'type': 'punctuation', 'alternatives': [{'content': '!'}]},
]}}
COMPLETED = {'TranscriptionJobStatus': 'COMPLETED', 'LanguageCode': 'en-US'}


class AmazonTranscribeTests(unittest.TestCase):
    def setUp(self):
        self.client, self.s3 = Mock(), Mock()
        self.s3.get_bucket_location.return_value = {'LocationConstraint': None}
        self.s3.get_object.side_effect = lambda **kwargs: {'Body': io.BytesIO(json.dumps(DOCUMENT).encode())}
        self.client.get_transcription_job.side_effect = error('BadRequestException', "The requested job couldn't be found.")
        self.client.start_transcription_job.return_value = {'TranscriptionJob': COMPLETED}
        self.patch = patch.object(aws, 'clients', return_value=(self.client, self.s3))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.audio = np.zeros(16000, dtype=np.float32)

    def test_uploads_valid_wav_and_uses_explicit_language(self):
        document, metadata = aws.transcribe_audio(self.audio, 'en')
        request = self.client.start_transcription_job.call_args.kwargs
        self.assertEqual(request['LanguageCode'], 'en-US')
        self.assertNotIn('IdentifyLanguage', request)
        self.assertNotIn('JobExecutionSettings', request)
        self.assertEqual(request['MediaSampleRateHertz'], 16000)
        self.assertEqual(request['OutputBucketName'], aws.TRANSCRIBE_BUCKET)
        upload = self.s3.put_object.call_args.kwargs
        with wave.open(io.BytesIO(upload['Body']), 'rb') as audio:
            self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (1, 16000, 16000))
        self.assertEqual(metadata['provider'], 'amazon')
        self.assertEqual(document, DOCUMENT)
        self.assertEqual(self.s3.get_object.call_args.kwargs['Key'], request['OutputKey'])

    def test_auto_detect_has_only_language_options(self):
        aws.transcribe_audio(self.audio, None)
        request = self.client.start_transcription_job.call_args.kwargs
        self.assertTrue(request['IdentifyLanguage'])
        self.assertEqual(request['LanguageOptions'], ['en-US', 'es-ES', 'fr-FR'])
        self.assertNotIn('LanguageCode', request)

    def test_restart_reattaches_running_job_without_upload_or_submission(self):
        self.client.get_transcription_job.side_effect = [
            {'TranscriptionJob': {'TranscriptionJobStatus': 'IN_PROGRESS'}},
            {'TranscriptionJob': COMPLETED}]
        with patch.object(aws.time, 'sleep'):
            aws.transcribe_audio(self.audio, 'en')
        self.s3.put_object.assert_not_called()
        self.client.start_transcription_job.assert_not_called()

    def test_completed_job_is_reused_and_language_changes_job_identity(self):
        self.client.get_transcription_job.side_effect = None
        self.client.get_transcription_job.return_value = {'TranscriptionJob': COMPLETED}
        _, first = aws.transcribe_audio(self.audio, 'en')
        _, second = aws.transcribe_audio(self.audio, 'en')
        _, third = aws.transcribe_audio(self.audio, 'fr')
        self.assertEqual(first['aws_job_name'], second['aws_job_name'])
        self.assertNotEqual(first['aws_job_name'], third['aws_job_name'])
        self.client.start_transcription_job.assert_not_called()

    def test_initial_failed_job_can_be_retried(self):
        self.client.get_transcription_job.side_effect = None
        self.client.get_transcription_job.return_value = {'TranscriptionJob': {'TranscriptionJobStatus': 'FAILED'}}
        aws.transcribe_audio(self.audio, 'en')
        self.client.delete_transcription_job.assert_called_once()
        self.client.start_transcription_job.assert_called_once()

    def test_new_failed_job_surfaces_reason_without_retry_loop(self):
        self.client.start_transcription_job.return_value = {'TranscriptionJob': {
            'TranscriptionJobStatus': 'FAILED', 'FailureReason': 'Unsupported media.'}}
        with self.assertRaisesRegex(aws.TranscriptionError, 'Unsupported media'):
            aws.transcribe_audio(self.audio, 'en')
        self.client.delete_transcription_job.assert_not_called()

    def test_timeout_preserves_remote_job_for_retry(self):
        self.client.get_transcription_job.side_effect = None
        self.client.get_transcription_job.return_value = {'TranscriptionJob': {'TranscriptionJobStatus': 'QUEUED'}}
        with patch.object(aws, 'TIMEOUT_SECONDS', 0):
            with self.assertRaisesRegex(aws.TranscriptionError, 'reconnect to the same AWS job'):
                aws.transcribe_audio(self.audio, 'en')
        self.client.delete_transcription_job.assert_not_called()

    def test_conflicting_submission_reattaches(self):
        self.client.get_transcription_job.side_effect = [
            error('BadRequestException', "The requested job couldn't be found."), {'TranscriptionJob': COMPLETED}]
        self.client.start_transcription_job.side_effect = error('ConflictException')
        aws.transcribe_audio(self.audio, 'en')
        self.client.start_transcription_job.assert_called_once()

    def test_region_mismatch_rejected_before_upload(self):
        self.s3.get_bucket_location.return_value = {'LocationConstraint': 'eu-west-1'}
        with self.assertRaisesRegex(aws.TranscriptionError, 'region must match'):
            aws.transcribe_audio(self.audio, 'en')
        self.s3.put_object.assert_not_called()

    def test_access_denied_is_not_treated_as_missing_job(self):
        self.client.get_transcription_job.side_effect = error('AccessDeniedException')
        with self.assertRaises(ClientError):
            aws.transcribe_audio(self.audio, 'en')
        self.s3.put_object.assert_not_called()
        message = safe_error(error('AccessDeniedException'))
        self.assertIn('Amazon Transcribe and S3 permissions', message)
        self.assertNotIn('Bedrock', message)

    def test_aws_words_preserve_punctuation_and_timestamps_in_service(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'audio.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\0\0' * 16000)
            with patch('audio_idp.services.transcription.whisper_model') as whisper:
                result = transcribe(path, None, provider='amazon')
            whisper.assert_not_called()
        self.assertEqual(result['language'], 'en')
        self.assertEqual(result['duration'], 1)
        self.assertEqual(result['segments'], [{'start': .1, 'end': .9, 'text': 'Hello, world!', 'speaker': 'Unknown'}])
        self.assertEqual(result['text'], '[0.10-0.90] Unknown: Hello, world!')

    def test_silent_audio_output_is_rejected(self):
        self.s3.get_object.side_effect = lambda **kwargs: {'Body': io.BytesIO(b'{"results":{"items":[]}}')}
        with patch('audio_idp.services.audio_validation.decode_audio', return_value=self.audio):
            with self.assertRaisesRegex(ValueError, 'No speech detected'):
                transcribe(Path('test.wav'), 'en', provider='amazon')


class TranscriptionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.w = Workspace(self.store)
        self.addCleanup(self.w.jobs.cloud.shutdown, wait=True)
        self.addCleanup(self.w.jobs.audio.shutdown, wait=True)
        self.batch = self.w.batch('Test batch')
        self.w.upload(self.batch, 'audio.wav', b'test audio', 'English')

    def wait(self):
        for future in tuple(self.w.jobs.futures):
            future.result(timeout=5)

    def test_amazon_choice_is_saved_and_used_by_retries(self):
        with patch('audio_idp.workflow.coordinator.transcribe', side_effect=[ValueError('temporary failure'),
                   {'text': 'Hello', 'language': 'en', 'provider': 'amazon'}]) as provider:
            self.w.transcribe_batch(self.batch, provider='amazon')
            self.wait()
            self.w.transcribe_batch(self.batch)
            self.wait()
        self.assertEqual(self.store.get(self.batch)['data']['transcription_provider'], 'amazon')
        self.assertEqual([call.kwargs['provider'] for call in provider.call_args_list], ['amazon', 'amazon'])
        self.assertEqual(len(self.w.transcripts(self.batch)), 1)

    def test_active_job_prevents_engine_change(self):
        recording = self.store.list('recording')[0]
        with self.store.connection() as db:
            db.execute("INSERT INTO jobs(id,kind,target,batch,status) VALUES('active','transcribe',?,?,'running')",
                       (recording['id'], self.batch))
        with self.assertRaisesRegex(ValueError, 'Wait for active'):
            self.w.transcribe_batch(self.batch, provider='amazon')
        self.assertNotIn('transcription_provider', self.store.get(self.batch)['data'])

    def test_existing_batch_defaults_to_whisper(self):
        with patch('audio_idp.workflow.coordinator.transcribe', return_value={'text': 'Hello', 'language': 'en'}) as provider:
            self.w.transcribe_batch(self.batch)
            self.wait()
        self.assertNotIn('provider', provider.call_args.kwargs)

    def test_invalid_engine_rejected(self):
        with self.assertRaisesRegex(ValueError, 'supported transcription engine'):
            self.w.transcribe_batch(self.batch, provider='other')


if __name__ == '__main__':
    unittest.main()
