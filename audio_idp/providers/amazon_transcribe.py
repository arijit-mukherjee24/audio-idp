"""Amazon Transcribe batch jobs, with stable names for retry/restart recovery."""
import hashlib
import json
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from audio_idp.config import TRANSCRIBE_BUCKET, TRANSCRIBE_REGION
from audio_idp.services.audio_validation import encode_wave

LANGUAGE_CODES = {'en': 'en-US', 'es': 'es-ES', 'fr': 'fr-FR'}
POLL_SECONDS = 3
TIMEOUT_SECONDS = 1800


class TranscriptionError(ValueError):
    pass


def clients():
    session = boto3.Session(profile_name='default')
    config = Config(connect_timeout=10, read_timeout=60, retries={'max_attempts': 2})
    return (session.client('transcribe', region_name=TRANSCRIBE_REGION, config=config),
            session.client('s3', region_name=TRANSCRIBE_REGION, config=config))


def get_job(client, name):
    try:
        return client.get_transcription_job(TranscriptionJobName=name)['TranscriptionJob']
    except ClientError as exc:
        error = exc.response['Error']
        if error['Code'] == 'BadRequestException' and "couldn't be found" in error.get('Message', ''):
            return None
        raise


def transcribe_audio(audio, language):
    """Upload validated mono audio; reuse the AWS job for identical input/settings.

    Input WAV and output JSON remain in S3 for recovery. Local deletion does not
    delete these objects; retention is managed separately in the bucket.
    """
    if not TRANSCRIBE_BUCKET:
        raise TranscriptionError('Set AUDIO_IDP_TRANSCRIBE_BUCKET before using Amazon Transcribe.')
    if language is not None and language not in LANGUAGE_CODES:
        raise TranscriptionError('Choose English, Spanish, French, or automatic language detection.')
    content = encode_wave(audio)
    settings = json.dumps(['v1', TRANSCRIBE_BUCKET, TRANSCRIBE_REGION, language], separators=(',', ':'))
    digest = hashlib.sha256(settings.encode() + b'\0' + content).hexdigest()
    name = 'audio-idp-' + digest
    input_key = f'audio-idp/input/{digest}.wav'
    output_key = f'audio-idp/output/{name}.json'
    client, s3 = clients()
    job = get_job(client, name)
    # Only explicit retry of an already-failed job recreates it. Running or
    # completed jobs are always reattached, including after a local restart.
    if job and job['TranscriptionJobStatus'] == 'FAILED':
        client.delete_transcription_job(TranscriptionJobName=name)
        job = None
    if job is None:
        location = s3.get_bucket_location(Bucket=TRANSCRIBE_BUCKET)['LocationConstraint'] or 'us-east-1'
        if location != TRANSCRIBE_REGION:
            raise TranscriptionError('The Transcribe region must match the S3 bucket region.')
        s3.put_object(Bucket=TRANSCRIBE_BUCKET, Key=input_key, Body=content, ContentType='audio/wav')
        request = dict(TranscriptionJobName=name, Media={'MediaFileUri': f's3://{TRANSCRIBE_BUCKET}/{input_key}'},
                       MediaFormat='wav', MediaSampleRateHertz=16000,
                       OutputBucketName=TRANSCRIBE_BUCKET, OutputKey=output_key)
        if language:
            request['LanguageCode'] = LANGUAGE_CODES[language]
        else:
            request.update(IdentifyLanguage=True, LanguageOptions=list(LANGUAGE_CODES.values()))
        try:
            job = client.start_transcription_job(**request)['TranscriptionJob']
        except ClientError as exc:
            if exc.response['Error']['Code'] != 'ConflictException':
                raise
            job = get_job(client, name)
            if job is None:
                raise TranscriptionError('An AWS job conflict occurred. Retry to reconnect to the job.') from exc

    deadline = time.monotonic() + TIMEOUT_SECONDS
    while job['TranscriptionJobStatus'] in ('QUEUED', 'IN_PROGRESS'):
        if time.monotonic() >= deadline:
            raise TranscriptionError('Amazon Transcribe is still processing. Retry to reconnect to the same AWS job.')
        time.sleep(POLL_SECONDS)
        job = get_job(client, name)
        if job is None:
            raise TranscriptionError('The AWS transcription job was removed. Retry this recording.')
    if job['TranscriptionJobStatus'] != 'COMPLETED':
        reason = job.get('FailureReason', 'Unknown transcription failure.')[:400]
        raise TranscriptionError('Amazon Transcribe failed: ' + reason)
    response = s3.get_object(Bucket=TRANSCRIBE_BUCKET, Key=output_key)
    with response['Body'] as body:
        document = json.load(body)
    return document, {'provider': 'amazon', 'aws_job_name': name,
                      'aws_region': TRANSCRIBE_REGION, 's3_bucket': TRANSCRIBE_BUCKET,
                      's3_input_key': input_key, 's3_output_key': output_key,
                      'language_code': job.get('LanguageCode')}


def words_from_result(document):
    words = []
    for item in document['results'].get('items', []):
        text = item['alternatives'][0]['content']
        if item['type'] == 'pronunciation':
            words.append({'start': float(item['start_time']), 'end': float(item['end_time']), 'text': ' ' + text})
        elif item['type'] == 'punctuation' and words:
            words[-1]['text'] += text
    return words
