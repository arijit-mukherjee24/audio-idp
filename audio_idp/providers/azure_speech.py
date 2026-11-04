"""Direct file upload to Azure Speech Fast Transcription (no Blob Storage)."""
import json
import os
from urllib.parse import urlsplit

import requests

from audio_idp.services.audio_validation import encode_wave

LANGUAGE_CODES = {'en': 'en-US', 'es': 'es-ES', 'fr': 'fr-FR'}
API_VERSION = '2025-10-15'


class AzureTranscriptionError(ValueError):
    pass


def endpoint():
    value = os.environ.get('AZURE_SPEECH_ENDPOINT', '').strip().rstrip('/')
    if not value:
        raise AzureTranscriptionError('Set AZURE_SPEECH_ENDPOINT to your Azure Speech resource endpoint, then restart the app.')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path):
        raise AzureTranscriptionError('AZURE_SPEECH_ENDPOINT must be an HTTPS resource base URL without a path or query.')
    return value


def auth_headers():
    mode = os.environ.get('AZURE_SPEECH_AUTH', 'key').strip().lower()
    if mode == 'key':
        key = os.environ.get('AZURE_SPEECH_KEY', '').strip()
        if not key:
            raise AzureTranscriptionError('Set AZURE_SPEECH_KEY locally, or use AZURE_SPEECH_AUTH=entra with an Azure login. Restart the app after configuring credentials.')
        return {'Ocp-Apim-Subscription-Key': key}
    if mode == 'entra':
        try:
            from azure.identity import DefaultAzureCredential
            from azure.core.exceptions import ClientAuthenticationError
        except ImportError:
            raise AzureTranscriptionError('Microsoft Entra authentication needs the optional requirements-azure.txt dependencies. Use API-key authentication or install those dependencies first.') from None
        try:
            with DefaultAzureCredential(exclude_interactive_browser_credential=True) as credential:
                token = credential.get_token('https://cognitiveservices.azure.com/.default').token
        except ClientAuthenticationError:
            raise AzureTranscriptionError('Azure login is unavailable. Sign in with Azure CLI or configure an application identity, then retry.') from None
        return {'Authorization': 'Bearer ' + token}
    raise AzureTranscriptionError('AZURE_SPEECH_AUTH must be key or entra.')


def transcribe_audio(audio, language):
    base = endpoint()
    if language is not None and language not in LANGUAGE_CODES:
        raise AzureTranscriptionError('Choose English, Spanish, French, or automatic language detection.')
    definition = {'locales': [LANGUAGE_CODES[language]] if language else list(LANGUAGE_CODES.values()),
                  'diarization': {'enabled': False}, 'profanityFilterMode': 'None'}
    try:
        # Do not retry POST automatically: a repeated request can be billed again.
        response = requests.post(base + '/speechtotext/transcriptions:transcribe',
                                 params={'api-version': API_VERSION}, headers=auth_headers(),
                                 files={'audio': ('audio.wav', encode_wave(audio), 'audio/wav'),
                                        'definition': (None, json.dumps(definition), 'application/json')},
                                 timeout=(10, 600), allow_redirects=False)
    except requests.Timeout:
        raise AzureTranscriptionError('Azure transcription timed out. Azure may have processed the audio; retrying can incur another charge.') from None
    except requests.RequestException:
        raise AzureTranscriptionError('Cannot reach Azure Speech. Check the endpoint, network, and resource firewall settings.') from None
    with response:
        if response.status_code != 200:
            hints = {400: 'Check supported locales and audio settings.',
                     401: 'Check your Speech key or Azure login.',
                     403: 'Check Speech data access permissions, authentication settings, and resource firewall rules.',
                     404: 'Check your Speech endpoint and Fast Transcription availability.',
                     429: 'Azure quota or rate limit reached. Wait before retrying.'}
            hint = hints.get(response.status_code, 'Check Azure Speech availability and resource configuration.')
            raise AzureTranscriptionError(f'Azure Speech returned HTTP {response.status_code}. {hint}')
        try:
            document = response.json()
        except ValueError:
            raise AzureTranscriptionError('Azure Speech returned an invalid JSON response. Retry the recording.') from None
    phrases = document.get('phrases') if isinstance(document, dict) else None
    if not isinstance(phrases, list):
        raise AzureTranscriptionError('Azure Speech returned a transcript without timestamped phrases.')
    # Auto-detection can label individual phrases. Report the language with the
    # greatest spoken duration using the app's existing single-language contract.
    durations = {}
    for phrase in phrases:
        locale = phrase.get('locale')
        if locale:
            durations[locale] = durations.get(locale, 0) + phrase.get('durationMilliseconds', 0)
    locale = max(durations, key=durations.get) if durations else LANGUAGE_CODES.get(language)
    return document, {'provider': 'azure', 'language_code': locale,
                      'azure_endpoint': base, 'azure_api_version': API_VERSION}


def words_from_result(document):
    words = []
    for phrase in document['phrases']:
        # Some responses omit word timing. Keep the phrase's own timestamps and
        # display text in that case rather than inventing individual word times.
        for item in phrase.get('words') or [phrase]:
            text = item.get('text', '').strip()
            if not text:
                continue
            start = float(item['offsetMilliseconds']) / 1000
            end = start + float(item['durationMilliseconds']) / 1000
            words.append({'start': start, 'end': end, 'text': ' ' + text})
    return words
