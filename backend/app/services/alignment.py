"""Forced word alignment for approved narration using WhisperX.

WhisperX is imported lazily so API/catalog routes and unit tests that do not
perform audio generation do not need to initialize PyTorch or download models.
All alignment is intentionally CPU based for predictable local Windows setup.
"""

from __future__ import annotations

import re
import threading
import unicodedata
import math
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


SUPPORTED_LANGUAGES = {"en": "en", "de": "de", "es": "es"}
MIN_WORD_SCORE = 0.10
_MODEL_LOCK = threading.Lock()
_ALIGNMENT_MODELS: dict[str, tuple[Any, Any]] = {}


class AlignmentError(RuntimeError):
    """Raised when narration cannot be reliably aligned to its script."""


@dataclass(frozen=True)
class WordTiming:
    index: int
    text: str
    start: float
    end: float
    score: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "score": None if self.score is None else round(self.score, 4),
        }


def _source_words(transcript: str) -> list[str]:
    # Keep punctuation and apostrophes attached to the approved source words.
    return re.findall(r"\S+", transcript, re.UNICODE)


def _canonical(value: str) -> str:
    """Remove separators/punctuation while retaining Unicode letters/digits."""
    folded = unicodedata.normalize("NFKC", value).casefold().replace("’", "'")
    return "".join(ch for ch in folded if ch.isalnum())


def _load_model(language: str) -> tuple[Any, Any]:
    if language not in SUPPORTED_LANGUAGES:
        raise AlignmentError(
            f"Unsupported alignment language '{language}'. Supported languages: en, de, es."
        )
    with _MODEL_LOCK:
        if language in _ALIGNMENT_MODELS:
            return _ALIGNMENT_MODELS[language]
        try:
            import whisperx
        except Exception as exc:  # pragma: no cover - environment-specific import
            raise AlignmentError(
                "WhisperX is unavailable. Install backend/requirements-alignment.txt "
                "in the active Python 3.12 environment."
            ) from exc
        try:
            model, metadata = whisperx.load_align_model(
                language_code=SUPPORTED_LANGUAGES[language], device="cpu"
            )
        except Exception as exc:  # pragma: no cover - download/model-specific
            raise AlignmentError(
                f"WhisperX alignment model could not be loaded for '{language}': {exc}"
            ) from exc
        _ALIGNMENT_MODELS[language] = (model, metadata)
        return model, metadata


def validate_word_timings(
    transcript: str,
    words: list[dict[str, Any]],
    duration: float,
    *,
    min_score: float = MIN_WORD_SCORE,
) -> list[WordTiming]:
    """Validate aligned words and map tokenizer splits back to source words.

    WhisperX can return a contraction as multiple tokens (or merge tokens).
    We compare the complete normalized character stream, then transfer measured
    token intervals onto the exact approved source tokens. No timing is inferred
    from source text length.
    """
    if not transcript.strip():
        raise AlignmentError("Cannot align an empty approved transcript")
    if not math.isfinite(duration) or duration <= 0:
        raise AlignmentError("Narration audio has an invalid duration")
    source = []
    for word in _source_words(transcript):
        if _canonical(word):
            source.append(word)
        elif source:
            # Preserve isolated punctuation exactly as approved.
            source[-1] += word
    if not source:
        raise AlignmentError("Approved transcript contains no alignable words")

    normalized_source = [_canonical(word) for word in source]
    expected_stream = "".join(normalized_source)
    aligned: list[tuple[str, float, float, float | None]] = []
    for item in words:
        raw = str(item.get("word", item.get("text", ""))).strip()
        token = _canonical(raw)
        if not token:
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AlignmentError(f"Aligned word has no valid timestamp: {raw!r}") from exc
        score_value = item.get("score")
        score = None if score_value is None else float(score_value)
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > duration + 0.03:
            raise AlignmentError(f"Aligned word timestamp is outside the audio: {raw!r}")
        if score is not None and (not math.isfinite(score) or score < min_score):
            raise AlignmentError(
                f"Unreliable alignment for '{raw}' (score {score:.3f}); refusing estimated captions."
            )
        aligned.append((token, start, end, score))

    aligned_stream = "".join(item[0] for item in aligned)
    if not aligned:
        raise AlignmentError("WhisperX returned no alignable words")
    similarity = SequenceMatcher(a=expected_stream, b=aligned_stream, autojunk=False).ratio()
    if similarity < 0.985 or expected_stream != aligned_stream:
        raise AlignmentError(
            "Audio/transcript mismatch: WhisperX aligned text does not cover the exact "
            f"approved transcript (character similarity {similarity:.3f})."
        )

    # Each aligned token covers a contiguous section of the punctuation-free
    # transcript stream. A source word can therefore receive multiple pieces.
    char_ranges: list[tuple[int, int, float, float, list[float]]] = []
    offset = 0
    for token, start, end, score in aligned:
        scores = [] if score is None else [score]
        char_ranges.append((offset, offset + len(token), start, end, scores))
        offset += len(token)

    result: list[WordTiming] = []
    source_offset = 0
    previous_start = -1.0
    previous_end = -1.0
    for index, (text, canonical) in enumerate(zip(source, normalized_source), 1):
        source_end = source_offset + len(canonical)
        overlaps = [
            token for token in char_ranges
            if token[0] < source_end and token[1] > source_offset
        ]
        if not overlaps:
            raise AlignmentError(f"WhisperX did not align approved word {text!r}")
        start = min(token[2] for token in overlaps)
        end = max(token[3] for token in overlaps)
        scores = [score for token in overlaps for score in token[4]]
        if start < previous_start or start < previous_end - 0.03:
            raise AlignmentError("WhisperX word timestamps are not monotonic")
        result.append(WordTiming(index, text, start, end, min(scores) if scores else None))
        source_offset = source_end
        previous_start = start
        previous_end = end
    if source_offset != len(expected_stream):
        raise AlignmentError("WhisperX alignment did not cover the full transcript")
    return result


def align_audio(
    audio_path: str | Path,
    transcript: str,
    language: str,
    *,
    duration: float | None = None,
) -> list[WordTiming]:
    """Force-align the exact approved transcript to final narration audio."""
    path = Path(audio_path)
    if not path.is_file():
        raise AlignmentError(f"Narration audio file is missing: {path}")
    if language not in SUPPORTED_LANGUAGES:
        raise AlignmentError(
            f"Unsupported alignment language '{language}'. Supported languages: en, de, es."
        )
    if not transcript.strip():
        raise AlignmentError("Cannot align an empty approved transcript")
    if duration is None:
        try:
            with wave.open(str(path), "rb") as wav_file:
                duration = wav_file.getnframes() / float(wav_file.getframerate())
        except Exception as exc:
            raise AlignmentError(f"Unable to read narration WAV '{path}': {exc}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise AlignmentError("Narration audio has an invalid duration")
    model, metadata = _load_model(language)
    try:
        import whisperx

        audio = whisperx.load_audio(str(path))
        aligned = whisperx.align(
            [{"text": transcript, "start": 0.0, "end": float(duration)}],
            model,
            metadata,
            audio,
            device="cpu",
            return_char_alignments=False,
        )
    except AlignmentError:
        raise
    except Exception as exc:  # pragma: no cover - model/audio-specific
        raise AlignmentError(f"WhisperX failed to align narration: {exc}") from exc
    raw_words = [
        word
        for segment in aligned.get("segments", [])
        for word in segment.get("words", [])
    ]
    return validate_word_timings(transcript, raw_words, float(duration))

