import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('AUDIO_IDP_DATA', ROOT / '.data'))
MODEL_CACHE = ROOT / '.models'
MODEL = 'us.anthropic.claude-sonnet-4-6'
REGION = 'us-east-1'
TRANSCRIBE_BUCKET = os.environ.get('AUDIO_IDP_TRANSCRIBE_BUCKET', 'am-sc-test-bucket')
TRANSCRIBE_REGION = os.environ.get('AUDIO_IDP_TRANSCRIBE_REGION', REGION)
TRANSCRIPTION_WORKERS = max(1, min(4, int(os.environ.get('AUDIO_IDP_WORKERS', '2'))))
CPU_THREADS = max(1, (os.cpu_count() or 4) // TRANSCRIPTION_WORKERS)
MAX_FIELDS = 10
