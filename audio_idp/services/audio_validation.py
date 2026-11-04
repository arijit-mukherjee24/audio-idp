from pathlib import Path
import io
import wave
import av
import numpy as np
MAX_BYTES=50*1024*1024
MAX_SECONDS=600


def encode_wave(audio):
    """Encode validated float samples as mono 16 kHz PCM for cloud services."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        output.writeframes((audio.clip(-1, 1) * 32767).astype('<i2').tobytes())
    return buffer.getvalue()

def decode_audio(path):
    # Decode once with a hard duration limit, including files with misleading headers.
    import av
    import numpy as np
    if Path(path).stat().st_size > MAX_BYTES:
        raise ValueError("Audio exceeds 50 MB.")
    chunks, samples = [], 0
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError("No audio stream found.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                chunk = converted.to_ndarray().flatten()
                samples += len(chunk)
                if samples > MAX_SECONDS * 16000:
                    raise ValueError("Audio exceeds the 10-minute limit.")
                chunks.append(chunk)
        for converted in resampler.resample(None):
            chunk = converted.to_ndarray().flatten()
            samples += len(chunk)
            chunks.append(chunk)
    if not samples or samples > MAX_SECONDS * 16000:
        raise ValueError("Audio is empty or exceeds 10 minutes.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0
