
import shutil

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas import VideoSpec


router = APIRouter(tags=["System"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "phase": 2,
        "ffmpeg_installed": bool(shutil.which("ffmpeg")),
        "ffprobe_installed": bool(shutil.which("ffprobe")),
        "gemini_key_configured": bool(settings.gemini_api_key),
    }


@router.get("/video-spec", response_model=VideoSpec)
def video_spec():
    return VideoSpec()


@router.get("/gemini/models")
def gemini_models():
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=400,
            detail="Set GEMINI_API_KEY in backend/.env first",
        )

    try:
        from google import genai

        client = genai.Client(
            api_key=settings.gemini_api_key
        )

        names = [
            model.name
            for model in client.models.list()
        ]

        return {
            "models": names,
            "configured_script_model": settings.gemini_script_model,
            "configured_tts_model": settings.gemini_tts_model,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Gemini model listing failed: "
                f"{type(exc).__name__}; "
                "check API key, permissions and connectivity"
            ),
        ) from exc
