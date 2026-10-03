"""Speech pace and coverage with faster-whisper. Stores statistics only, never the transcript text."""
from __future__ import annotations

import tempfile
from pathlib import Path

from .media import extract_audio

MODEL_SIZE = "base"  # ~150 MB, downloaded on first use; fine on CPU


def spans(path: Path) -> list[tuple[float, float]] | None:
    """(start, end) of each speech segment, or None when faster-whisper is not installed. Times only, no text."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "speech.wav", sr=16000)
        segments, _ = model.transcribe(str(wav), vad_filter=True, word_timestamps=False)
        return [(round(seg.start, 2), round(seg.end, 2)) for seg in segments]


def analyze(path: Path, duration: float) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"status": "not_measured", "reason": "faster-whisper is not installed"}
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory() as td:
        wav = extract_audio(path, Path(td) / "speech.wav", sr=16000)
        segments, info = model.transcribe(str(wav), vad_filter=True, word_timestamps=False)
        segments = list(segments)
    if not segments:
        return {"status": "measured", "has_speech": False}
    words = sum(len(s.text.split()) for s in segments)
    spoken = sum(s.end - s.start for s in segments)
    return {
        "status": "measured",
        "has_speech": True,
        "language": info.language,
        "words_per_minute": round(words / spoken * 60, 1) if spoken > 0 else None,
        "speech_coverage": round(min(1.0, spoken / duration), 3),
        "first_speech_sec": round(segments[0].start, 2),
        "segment_count": len(segments),
    }
