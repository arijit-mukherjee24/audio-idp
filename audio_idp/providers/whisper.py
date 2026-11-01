from functools import lru_cache
from threading import Lock
from audio_idp.config import MODEL_CACHE, TRANSCRIPTION_WORKERS, CPU_THREADS

_lock = Lock()

class ModelDownloadError(RuntimeError):
    pass

@lru_cache(maxsize=2)
def _load(size, device):
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import LocalEntryNotFoundError
    options = dict(device=device, compute_type='int8' if device == 'cpu' else 'float16',
                   download_root=str(MODEL_CACHE), num_workers=TRANSCRIPTION_WORKERS, cpu_threads=CPU_THREADS)
    try:
        return WhisperModel(size, local_files_only=True, **options)
    except LocalEntryNotFoundError:
        try:
            return WhisperModel(size, **options)
        except (OSError, LocalEntryNotFoundError) as exc:
            raise ModelDownloadError('The transcription model is not available. Connect to the internet for its first download, then retry.') from exc

def whisper_model(size='small', device='cpu'):
    # Serialize first initialization; lru_cache alone permits duplicate initial loads.
    with _lock:
        return _load(size, device)

whisper_model.cache_clear = _load.cache_clear
