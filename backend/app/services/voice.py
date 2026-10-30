

"""Voice generation with Gemini TTS, Edge fallback, and FFmpeg."""

import asyncio
import json
import shutil
import subprocess
import uuid
import wave
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.creative import CreativePlan, LANGUAGES
from app.services.alignment import AlignmentError, align_audio


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

TARGET_SECONDS = 15.0
SAMPLE_RATE = 24000
CAPTION_FPS = 24

# Maximum allowed FFmpeg playback-speed adjustment.
MAX_SPEEDUP = 1.20

# Reserve a small tail to prevent clipping the last word.
SPEECH_LIMIT = TARGET_SECONDS - 0.25

# Edge-TTS supports explicit speaking-rate adjustment.
EDGE_SPEAKING_RATE = "+15%"

VOICE_OPTIONS = {
    "en": {
        "gemini": ["Kore", "Puck", "Aoede", "Charon"],
        "edge": [
            "en-US-JennyNeural",
            "en-GB-SoniaNeural",
        ],
    },
    "de": {
        "gemini": ["Kore", "Puck", "Aoede", "Charon"],
        "edge": [
            "de-DE-KatjaNeural",
            "de-DE-ConradNeural",
        ],
    },
    "es": {
        "gemini": ["Kore", "Puck", "Aoede", "Charon"],
        "edge": [
            "es-ES-ElviraNeural",
            "es-MX-DaliaNeural",
        ],
    },
}


# ---------------------------------------------------------
# Request and Caption Models
# ---------------------------------------------------------

class CaptionCue(BaseModel):
    index: int
    text: str
    start: float = Field(ge=0)
    end: float = Field(le=TARGET_SECONDS)


def group_aligned_words(words: list[dict], *, max_words: int = 6) -> list[CaptionCue]:
    """Group measured word intervals into readable, naturally timed captions."""
    if not words:
        raise AlignmentError("Cannot create captions without aligned words")
    groups: list[list[dict]] = []
    current: list[dict] = []
    punctuation = (".", "!", "?", ";", ":", "…", ",")

    for word in words:
        if current:
            pause = float(word["start"]) - float(current[-1]["end"])
            current_text = " ".join(item["text"] for item in current)
            proposed_text = f"{current_text} {word['text']}"
            should_break = (
                len(current) >= max_words
                or (len(current) >= 2 and pause >= 0.45)
                or (len(current) >= 2 and current[-1]["text"].endswith(punctuation))
                or (len(current) >= 2 and len(proposed_text) > 44)
            )
            if should_break:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)

    # Very short captions are hard to read. Merge only when the measured pause
    # is small and the combined phrase remains within the visual word/line cap.
    index = 0
    while index < len(groups):
        group = groups[index]
        duration = float(group[-1]["end"]) - float(group[0]["start"])
        if duration < 0.48 and len(groups) > 1:
            neighbor = index - 1 if index > 0 else index + 1
            left, right = (groups[neighbor], group) if neighbor < index else (group, groups[neighbor])
            gap = float(right[0]["start"]) - float(left[-1]["end"])
            if len(left) + len(right) <= max_words and gap < 0.35:
                merged = left + right
                first, second = sorted((index, neighbor))
                groups[first:second + 1] = [merged]
                index = max(0, first - 1)
                continue
        index += 1

    cues = []
    previous_end = 0.0
    for number, group in enumerate(groups, 1):
        start = float(group[0]["start"])
        end = float(group[-1]["end"])
        # Quantize overlay boundaries to frame boundaries; this keeps them
        # tied to measured word timing while preventing sub-frame flicker.
        start = max(previous_end, round(start * CAPTION_FPS) / CAPTION_FPS)
        end = round(end * CAPTION_FPS) / CAPTION_FPS
        if end <= start:
            end = start + 1 / CAPTION_FPS
        cues.append(CaptionCue(
            index=number,
            text=" ".join(str(item["text"]) for item in group),
            start=round(start, 3),
            end=round(end, 3),
        ))
        previous_end = end
    return cues


class VoiceRequest(BaseModel):
    product_id: str
    language: str = "en"
    voice: str = "Kore"
    plan: CreativePlan | None = None


# ---------------------------------------------------------
# FFmpeg Helpers
# ---------------------------------------------------------

def require_ffmpeg():
    """Ensure FFmpeg and ffprobe are installed."""

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "FFmpeg and ffprobe are required. "
            "Install FFmpeg and restart the terminal."
        )


def run_command(args: list[str]):
    """Execute FFmpeg and raise a readable error if it fails."""

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg processing failed: "
            + result.stderr[-1500:]
        )


def audio_duration(path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return float(result.stdout.strip())


def required_speedup(duration: float) -> float:
    """
    Calculate the speed adjustment required to fit
    narration within the available speech window.
    """

    if duration <= 0:
        raise RuntimeError(
            "Generated audio has invalid duration"
        )

    return max(1.0, duration / SPEECH_LIMIT)


def fits_duration_limit(path: Path) -> bool:
    """
    Check whether an audio file can fit naturally
    without exceeding MAX_SPEEDUP.
    """

    duration = audio_duration(path)
    speed = required_speedup(duration)

    print(
        f"TTS duration: {duration:.2f}s | "
        f"Required speedup: {speed:.2f}x"
    )

    return speed <= MAX_SPEEDUP


# ---------------------------------------------------------
# Gemini TTS
# ---------------------------------------------------------

def gemini_tts(
    text: str,
    language: str,
    voice: str,
    output: Path,
):
    """Generate spoken narration using Gemini TTS."""

    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing"
        )

    client = genai.Client(
        api_key=settings.gemini_api_key
    )

    # Send only the approved narration. A long instruction prompt can
    # be spoken aloud by the TTS model as part of the audio.
    prompt = text.strip()
    if not prompt:
        raise ValueError("Cannot synthesize an empty voiceover")

    response = client.models.generate_content(
        model=settings.gemini_tts_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        ),
    )

    pcm = None

    for candidate in response.candidates or []:
        if not candidate.content:
            continue

        for part in candidate.content.parts or []:
            if part.inline_data and part.inline_data.data:
                pcm = part.inline_data.data
                break

        if pcm:
            break

    if not pcm:
        raise RuntimeError(
            "Gemini returned no audio"
        )

    # Gemini TTS normally returns 24 kHz mono PCM.
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)


# ---------------------------------------------------------
# Edge-TTS Fallback
# ---------------------------------------------------------

async def edge_tts_async(
    text: str,
    language: str,
    output: Path,
):
    """
    Generate narration using Edge-TTS.

    A moderate speaking-rate increase helps fit
    a 35–45-word script into a 15-second video.
    """

    import edge_tts

    selected_voice = {
        "en": "en-GB-SoniaNeural",
        "de": "de-DE-KatjaNeural",
        "es": "es-ES-ElviraNeural",
    }[language]


    communicate = edge_tts.Communicate(
        text=text,
        voice=selected_voice,
        rate="-3%",
        pitch="-1Hz",
        volume="+0%",
    )
    await communicate.save(str(output))


def edge_tts_generate(
    text: str,
    language: str,
    output: Path,
):
    """Run Edge-TTS from the synchronous pipeline."""

    asyncio.run(
        edge_tts_async(
            text,
            language,
            output,
        )
    )


# ---------------------------------------------------------
# Final Audio Processing
# ---------------------------------------------------------

def make_exact_duration(
    source: Path,
    destination: Path,
) -> dict:
    """
    Fit the narration into exactly 15 seconds.

    Never exceed MAX_SPEEDUP.
    Pad remaining time with silence.
    """

    original = audio_duration(source)

    if original <= 0:
        raise RuntimeError(
            "Generated audio has invalid duration"
        )

    speed = required_speedup(original)

    if speed > MAX_SPEEDUP:
        raise RuntimeError(
            f"Narration is too long ({original:.2f}s). "
            f"Required speedup {speed:.2f}x exceeds "
            f"the allowed {MAX_SPEEDUP:.2f}x. "
            "A faster delivery or revised script is required."
        )

    run_command(
        [
            "ffmpeg",
            "-y",
            "-i", str(source),
            "-af",
            (
                f"atempo={speed:.6f},"
                "apad,"
                f"atrim=0:{TARGET_SECONDS},"
                "asetpts=N/SR/TB"
            ),
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(destination),
        ]
    )

    final_duration = audio_duration(
        destination
    )

    speech_duration = original / speed

    if abs(final_duration - TARGET_SECONDS) > 0.03:
        raise RuntimeError(
            f"Final audio is {final_duration:.3f}s, "
            "not 15 seconds"
        )

    return {
        "original_duration": round(
            original, 3
        ),
        "speech_duration": round(
            speech_duration, 3
        ),
        "final_duration": round(
            final_duration, 3
        ),
        "speed_factor": round(
            speed, 3
        ),
    }


# ---------------------------------------------------------
# Caption Generation
# ---------------------------------------------------------

# ---------------------------------------------------------
# Main Voice Pipeline
# ---------------------------------------------------------

def synthesize_voice(
    plan: CreativePlan,
    language: str,
    voice: str,
    product_id: str,
) -> dict:
    """
    Generate narration using Gemini first.

    If Gemini fails or produces excessively long
    audio, retry using Edge-TTS.

    Preserve the brand-compliant script.
    """

    require_ffmpeg()

    if language not in VOICE_OPTIONS:
        raise ValueError(
            "Unsupported language"
        )

    if voice not in VOICE_OPTIONS[language]["gemini"]:
        raise ValueError(
            "Unsupported Gemini voice"
        )

    job_id = str(
        uuid.uuid4()
    )

    output_dir = (
        settings.media_root
        / "voice"
        / job_id
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    gemini_output = (
        output_dir / "gemini.wav"
    )

    edge_output = (
        output_dir / "edge.mp3"
    )

    final_output = (
        output_dir / "narration.wav"
    )

    engine = "gemini"
    fallback_reason = None

    # -----------------------------------------------------
    # Attempt Gemini TTS
    # -----------------------------------------------------

    try:
        gemini_tts(
            plan.voiceover,
            language,
            voice,
            gemini_output,
        )

        if not fits_duration_limit(
            gemini_output
        ):
            raise RuntimeError(
                "Gemini narration exceeded "
                "the allowed duration"
            )

        source = gemini_output

    except Exception as exc:
        print(
            "Gemini TTS failed or exceeded "
            f"duration: {type(exc).__name__}: {exc}"
        )

        fallback_reason = (
            f"{type(exc).__name__}: {str(exc)[:250]}"
        )

        engine = "edge"

        # -------------------------------------------------
        # Retry using faster Edge-TTS
        # -------------------------------------------------

        edge_tts_generate(
            plan.voiceover,
            language,
            edge_output,
        )

        source = edge_output

        if not fits_duration_limit(
            edge_output
        ):
            duration = audio_duration(
                edge_output
            )

            raise RuntimeError(
                "Both Gemini and Edge-TTS failed "
                "to produce a natural 15-second "
                "narration. "
                f"Edge duration: {duration:.2f}s. "
                "The script must be revised while "
                "preserving brand requirements."
            )

    # -----------------------------------------------------
    # Normalize audio to 15 seconds
    # -----------------------------------------------------

    metrics = make_exact_duration(
        source,
        final_output,
    )

    # -----------------------------------------------------
    # Forced alignment and caption grouping
    # -----------------------------------------------------

    try:
        word_timings = align_audio(
            final_output,
            plan.voiceover,
            language,
            duration=metrics["final_duration"],
        )
    except AlignmentError as exc:
        raise RuntimeError(f"Narration alignment failed: {exc}") from exc

    words_path = output_dir / "words.json"
    word_records = [word.as_dict() for word in word_timings]
    words_path.write_text(
        json.dumps(word_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cues = group_aligned_words(word_records)

    captions_path = (
        output_dir / "captions.json"
    )

    captions_path.write_text(
        json.dumps(
            [
                cue.model_dump()
                for cue in cues
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # -----------------------------------------------------
    # Save metadata
    # -----------------------------------------------------

    metadata = {
        "job_id": job_id,
        "product_id": product_id,
        "language": language,
        "requested_voice": voice,
        "engine_used": engine,
        "fallback_reason": fallback_reason,
        "audio_file": str(
            final_output
        ),
        "captions_file": str(
            captions_path
        ),
        "words_file": str(words_path),
        "voiceover": plan.voiceover,
        "captions": [
            cue.model_dump()
            for cue in cues
        ],
        "words": word_records,
        "alignment": {
            "provider": "whisperx",
            "status": "aligned",
            "language": language,
            "device": "cpu",
            "word_count": len(word_records),
            "caption_count": len(cues),
            "timing_source": "forced_alignment",
        },
        **metrics,
    }

    metadata_path = (
        output_dir / "metadata.json"
    )

    metadata_path.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return metadata
