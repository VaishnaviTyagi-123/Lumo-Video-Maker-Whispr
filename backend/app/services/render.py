
"""Render 15-second vertical product videos with Pillow and FFmpeg."""

import json
import math
import shutil
import subprocess
import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.core.config import BACKEND_ROOT, settings
from app.services.creative import CreativePlan, validate_plan


WIDTH = 1080
HEIGHT = 1920
FPS = 24
SCENE_SECONDS = 3
VIDEO_SECONDS = 15

COLORS = [
    ("#F3EEE6", "#3E4B43"),
    ("#E9E5DB", "#46574E"),
    ("#F1E8DD", "#51483E"),
    ("#E8ECE5", "#40544A"),
    ("#EDE6DB", "#3F4B43"),
]


def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            "FFmpeg failed: " + result.stderr[-2000:]
        )


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "stream=width,height,codec_name,codec_type",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    stream = next(
        (item for item in data["streams"] if item.get("codec_type") == "video"),
        None,
    )
    if stream is None:
        raise RuntimeError("Rendered file has no video stream")
    return {
        "width": stream["width"],
        "height": stream["height"],
        "codec": stream["codec_name"],
        "has_audio": any(item.get("codec_type") == "audio" for item in data["streams"]),
        "duration": float(data["format"]["duration"]),
    }


def find_font(bold: bool = False) -> str:
    candidates = (
        [
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/segoeuib.ttf"),
        ]
        if bold
        else [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
        ]
    )
    candidates += [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    raise RuntimeError("No suitable TrueType font found")


def font(size: int, bold: bool = False):
    return ImageFont.truetype(find_font(bold), size)


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    selected_font,
    max_width: int,
) -> list[str]:
    lines = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=selected_font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    y: int,
    selected_font,
    color: str,
    spacing: int = 16,
) -> int:
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=selected_font)
        line_width = bbox[2] - bbox[0]
        draw.text(
            ((WIDTH - line_width) / 2, y),
            line,
            font=selected_font,
            fill=color,
        )
        y += selected_font.size + spacing
    return y


def resolve_product_image(image_value: str) -> Path:
    """
    Resolve a catalog image relative to backend/data.

    Prevent absolute paths and traversal outside that directory.
    """
    data_root = (BACKEND_ROOT / "data").resolve()
    image_path = (data_root / image_value).resolve()

    if not image_path.is_relative_to(data_root):
        raise ValueError("Invalid product image path")

    if not image_path.is_file():
        raise FileNotFoundError(
            f"Product image not found: {image_path}"
        )

    return image_path


def make_scene_card(
    image_path: Path,
    product_name: str,
    caption: str,
    index: int,
    destination: Path,
):
    background, ink = COLORS[index - 1]

    canvas = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(canvas)

    small = font(35)
    heading = font(66, bold=True)
    caption_font = font(57, bold=True)

    draw.text(
        (90, 100),
        "LUMO LIVING",
        fill=ink,
        font=font(40, bold=True),
    )

    draw.line(
        (90, 174, WIDTH - 90, 174),
        fill=ink,
        width=2,
    )

    title_lines = wrap_text(
        draw, product_name, heading, WIDTH - 180
    )
    draw_centered_text(
        draw, title_lines, 260, heading, ink
    )

    with Image.open(image_path) as original:
        product = ImageOps.contain(
            original.convert("RGBA"),
            (820, 900),
            Image.Resampling.LANCZOS,
        )

    product_x = (WIDTH - product.width) // 2
    product_y = 590 + (index % 2) * 35

    canvas.paste(
        product,
        (product_x, product_y),
        product,
    )

    draw.text(
        (90, 1825),
        f"0{index} / 05",
        font=small,
        fill=ink,
    )

    canvas.save(destination, "PNG")



def make_caption_overlay(text: str, destination: Path) -> None:
    """Create one transparent subtitle overlay for timed compositing."""
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    caption_font = font(57, bold=True)
    lines = wrap_text(draw, text, caption_font, WIDTH - 180)
    while len(lines) > 3 and caption_font.size > 35:
        caption_font = font(caption_font.size - 4, bold=True)
        lines = wrap_text(draw, text, caption_font, WIDTH - 180)
    if len(lines) > 3:
        raise ValueError("Caption is too long to fit in the video")
    draw.rounded_rectangle(
        (65, 1450, WIDTH - 65, 1760),
        radius=38,
        fill=(255, 255, 255, 240),
    )
    height = len(lines) * (caption_font.size + 15)
    draw_centered_text(
        draw, lines, 1605 - height // 2, caption_font, "#3E4B43", spacing=15
    )
    canvas.save(destination, "PNG")


def checked_caption_cues(voice_metadata: dict, plan: CreativePlan) -> list[dict]:
    """Validate forced-aligned caption coverage and timing before rendering."""
    cues = voice_metadata.get("captions")
    alignment = voice_metadata.get("alignment", {})
    if alignment.get("status") != "aligned" or alignment.get("timing_source") != "forced_alignment":
        raise ValueError("Voice job does not contain verified forced-alignment metadata")
    if not isinstance(cues, list) or not cues:
        raise ValueError("Voice job must contain at least one aligned caption cue")
    combined = " ".join(str(cue.get("text", "")) for cue in cues)
    normalize = lambda text: " ".join(text.split())
    if normalize(combined) != normalize(plan.voiceover):
        raise ValueError("Voice captions do not reproduce the approved voiceover")
    previous_end = -1.0
    for index, cue in enumerate(cues, 1):
        start = float(cue["start"])
        end = float(cue["end"])
        if cue.get("index") != index:
            raise ValueError("Voice captions are out of order")
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > VIDEO_SECONDS + 0.001:
            raise ValueError("Invalid voice caption timestamps")
        if start < previous_end - 0.001:
            raise ValueError("Voice captions overlap")
        previous_end = end
    words = voice_metadata.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("Voice job is missing aligned word-level timing metadata")
    if alignment.get("word_count") != len(words) or alignment.get("caption_count") != len(cues):
        raise ValueError("Voice alignment metadata counts do not match saved timings")
    word_text = " ".join(str(word.get("text", "")) for word in words)
    if normalize(word_text) != normalize(plan.voiceover):
        raise ValueError("Aligned words do not reproduce the approved voiceover")
    previous_word_end = -1.0
    for word in words:
        start = float(word["start"])
        end = float(word["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > VIDEO_SECONDS + 0.001:
            raise ValueError("Invalid aligned word timestamps")
        if start < previous_word_end - 0.03:
            raise ValueError("Aligned word timestamps are not monotonic")
        previous_word_end = end
    return cues


def mux_with_timed_captions(
    silent_video: Path,
    audio_path: Path,
    cues: list[dict],
    work_dir: Path,
    final_path: Path,
) -> None:
    """Overlay voice-caption PNGs only during their corresponding cue times."""
    overlay_paths = []
    for index, cue in enumerate(cues, 1):
        overlay_path = work_dir / f"caption_{index}.png"
        make_caption_overlay(cue["text"], overlay_path)
        overlay_paths.append(overlay_path)

    args = ["-i", str(silent_video), "-i", str(audio_path)]
    for path in overlay_paths:
        args.extend(["-loop", "1", "-framerate", str(FPS), "-i", str(path)])

    filters = []
    source = "[0:v]"
    for index, cue in enumerate(cues, 1):
        destination = f"[v{index}]"
        start = float(cue["start"])
        end = float(cue["end"])
        # PNG input 2 is caption 1; input 6 is caption 5.
        filters.append(
            f"{source}[{index + 1}:v]overlay=0:0:"
            f"enable='gte(t,{start:.3f})*lt(t,{end:.3f})':"
            f"shortest=1{destination}"
        )
        source = destination

    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", source, "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", str(VIDEO_SECONDS), "-movflags", "+faststart",
        str(final_path),
    ])
    run_ffmpeg(args)

def animation_filter(animation: str) -> str:
    """
    FFmpeg zoompan animations for one 3-second scene.

    Motion is intentionally subtle to match the brand.
    """
    frames = FPS * SCENE_SECONDS

    effects = {
        "slow_zoom": (
            "z='min(1.0+on*0.00065,1.05)':"
            "x='iw/2-iw/zoom/2':"
            "y='ih/2-ih/zoom/2'"
        ),
        "slow_pan": (
            "z='1.06':"
            "x='(iw-iw/zoom)*on/72':"
            "y='ih/2-ih/zoom/2'"
        ),
        "fade": (
            "z='1.0':x='0':y='0'"
        ),
        "gentle_float": (
            "z='1.04':"
            "x='iw/2-iw/zoom/2':"
            "y='max(0,min(ih-ih/zoom,"
            "ih/2-ih/zoom/2+sin(on/15)*5))'"
        ),
        "static": (
            "z='1.0':x='0':y='0'"
        ),
    }

    motion = effects[animation]

    filters = (
        f"zoompan={motion}:"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "format=yuv420p"
    )

    if animation == "fade":
        filters += ",fade=t=in:st=0:d=0.35"

    return filters


def render_scene(
    card_path: Path,
    animation: str,
    output_path: Path,
):
    run_ffmpeg(
        [
            "-loop", "1",
            "-framerate", str(FPS),
            "-i", str(card_path),
            "-vf", animation_filter(animation),
            "-frames:v", str(FPS * SCENE_SECONDS),
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "21",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            str(output_path),
        ]
    )


def render_product_video(
    product: dict,
    plan: CreativePlan,
    language: str,
    voice_job_id: str,
) -> dict:
    """
    Render a complete 15-second product video.

    Returns video metadata and the saved output path.
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg and ffprobe are required")

    violations = validate_plan(plan, product, language)
    if violations:
        raise ValueError(
            "Creative plan failed validation: "
            + "; ".join(violations)
        )

    try:
        safe_voice_id = str(uuid.UUID(voice_job_id))
    except ValueError as exc:
        raise ValueError("Invalid voice job ID") from exc

    voice_dir = settings.media_root / "voice" / safe_voice_id
    audio_path = voice_dir / "narration.wav"
    metadata_path = voice_dir / "metadata.json"

    if not audio_path.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("Voice job files not found")

    voice_metadata = json.loads(
        metadata_path.read_text(encoding="utf-8")
    )

    if voice_metadata.get("product_id") != product["id"]:
        raise ValueError("Voice job belongs to another product")

    if voice_metadata.get("language") != language:
        raise ValueError("Voice job language does not match")

    if voice_metadata.get("voiceover") != plan.voiceover:
        raise ValueError(
            "Voice job narration differs from the creative plan"
        )

    image_path = resolve_product_image(product["image"])

    render_id = str(uuid.uuid4())
    work_dir = settings.media_root / "videos" / render_id
    work_dir.mkdir(parents=True, exist_ok=True)

    scene_paths = []

    for scene in plan.scenes:
        card_path = work_dir / f"card_{scene.index}.png"
        scene_path = work_dir / f"scene_{scene.index}.mp4"

        make_scene_card(
            image_path=image_path,
            product_name=product["name"],
            caption="",
            index=scene.index,
            destination=card_path,
        )

        render_scene(
            card_path,
            scene.animation,
            scene_path,
        )

        scene_paths.append(scene_path)

    concat_path = work_dir / "concat.txt"
    concat_path.write_text(
        "".join(
            f"file '{path.name}'\n"
            for path in scene_paths
        ),
        encoding="utf-8",
    )

    silent_video = work_dir / "silent.mp4"

    run_ffmpeg(
        [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_path),
            "-c", "copy",
            str(silent_video),
        ]
    )

    cues = checked_caption_cues(voice_metadata, plan)
    final_path = work_dir / "final.mp4"
    mux_with_timed_captions(
        silent_video, audio_path, cues, work_dir, final_path
    )

    details = probe_video(final_path)

    if details["width"] != WIDTH or details["height"] != HEIGHT:
        raise RuntimeError("Incorrect rendered resolution")
    if not details["has_audio"]:
        raise RuntimeError("Rendered video has no audio stream")

    if abs(details["duration"] - VIDEO_SECONDS) > 0.15:
        raise RuntimeError(
            f"Incorrect video duration: {details['duration']}"
        )

    metadata = {
        "render_id": render_id,
        "product_id": product["id"],
        "voice_job_id": safe_voice_id,
        "language": language,
        "video_file": str(final_path),
        "scene_count": len(plan.scenes),
        "width": details["width"],
        "height": details["height"],
        "duration": details["duration"],
        "codec": details["codec"],
        "caption_source": "whisperx_forced_alignment",
    }

    (work_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    return metadata
