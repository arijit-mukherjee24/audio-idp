from pathlib import Path
from audio_idp.providers.whisper import whisper_model, ModelDownloadError
MAX_BYTES = 50 * 1024 * 1024
MAX_SECONDS = 600
LANGUAGES = {"English": "en", "Spanish": "es", "French": "fr"}
FORMATS = ["mp3", "wav", "m4a", "flac", "ogg", "webm"]
PROVIDERS = {'whisper': 'Whisper (local)', 'amazon': 'Amazon Transcribe', 'azure': 'Azure Speech'}

def label_words(words, turns):
    """Assign by maximum overlap; retain Unknown when no speaker overlaps."""
    rows = []
    for word in words:
        overlaps = [(max(0, min(word["end"], end) - max(word["start"], start)), speaker)
                    for start, end, speaker in turns]
        overlap, speaker = max(overlaps, default=(0, "Unknown"))
        speaker = speaker if overlap > 0 else "Unknown"
        if rows and rows[-1]["speaker"] == speaker and word["start"] - rows[-1]["end"] < 1.5:
            rows[-1]["end"] = word["end"]
            rows[-1]["text"] += word["text"]
        else:
            rows.append(dict(word, speaker=speaker))
    for row in rows:
        row["text"] = row["text"].strip()
    return rows


def transcribe(path, language, size="small", device="cpu", speakers=False, *, provider='whisper'):
    if provider not in PROVIDERS:
        raise ValueError('Choose a supported transcription engine.')
    from audio_idp.services.audio_validation import decode_audio
    audio = decode_audio(path)
    samples = len(audio)
    if speakers:
        raise ValueError("Speaker labeling is not enabled in this workspace.")
    metadata = {'provider': provider}
    if provider != 'whisper':
        if provider == 'amazon':
            from audio_idp.providers.amazon_transcribe import transcribe_audio, words_from_result
        else:
            from audio_idp.providers.azure_speech import transcribe_audio, words_from_result
        document, metadata = transcribe_audio(audio, language)
        words = words_from_result(document)
        detected_language = (metadata.get('language_code') or language or '').split('-')[0]
    else:
        segments, info = whisper_model(size, device).transcribe(
            audio, language=language, vad_filter=True, word_timestamps=True)
        detected_language = info.language
        words = []
        for segment in segments:
            words.extend({"start": w.start, "end": w.end, "text": w.word} for w in segment.words or [])
    if not words:
        raise ValueError("No speech detected. Try a clearer recording.")
    rows = label_words(words, [])
    return {**metadata, "language": detected_language, "duration": samples / 16000, "segments": rows,
            "text": "\n".join(f'[{r["start"]:.2f}-{r["end"]:.2f}] {r["speaker"]}: {r["text"]}' for r in rows)}
