
# backend/app/api/voice.py

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product
from app.services.creative import (
    CreativePlan,
    run_creative_pipeline,
    validate_plan,
)
from app.services.voice import (
    VOICE_OPTIONS,
    VoiceRequest,
    synthesize_voice,
)


router = APIRouter(
    prefix="/voice",
    tags=["Voice Generation (Phase 3)"],
)


@router.get("/voices")
def list_voices():
    return VOICE_OPTIONS


@router.post("/generate")
def generate_voice(
    payload: VoiceRequest,
    db: Session = Depends(get_db),
):
    if payload.language not in VOICE_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail="Unsupported language",
        )

    product = db.get(Product, payload.product_id)
    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    product_data = {
        key: getattr(product, key)
        for key in (
            "id",
            "name",
            "category",
            "description",
            "features",
            "sustainability",
            "image",
        )
    }

    if payload.plan is not None:
        plan = payload.plan

        violations = validate_plan(
            plan, product_data, payload.language
        )

        if violations:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Plan failed brand validation",
                    "violations": violations,
                },
            )
    else:
        try:
            result = run_creative_pipeline(
                product_data, payload.language
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Creative plan generation failed: "
                    + type(exc).__name__
                ),
            ) from exc

        if not result["approved"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Creative plan was rejected",
                    "violations": result["violations"],
                },
            )

        plan = CreativePlan.model_validate(result["plan"])

    try:
        return synthesize_voice(
            plan=plan,
            language=payload.language,
            voice=payload.voice,
            product_id=payload.product_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Voice generation failed: "
                + type(exc).__name__
            ),
        ) from exc


def get_voice_job_directory(job_id: str) -> Path:
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Invalid job ID"
        )

    directory = (
        settings.media_root / "voice" / str(parsed_id)
    )

    if not directory.is_dir():
        raise HTTPException(
            status_code=404, detail="Voice job not found"
        )

    return directory


@router.get("/{job_id}")
def get_voice_job(job_id: str):
    directory = get_voice_job_directory(job_id)
    metadata_path = directory / "metadata.json"

    if not metadata_path.is_file():
        raise HTTPException(
            status_code=404, detail="Metadata not found"
        )

    return json.loads(
        metadata_path.read_text(encoding="utf-8")
    )


@router.get("/{job_id}/audio")
def download_voice_audio(job_id: str):
    directory = get_voice_job_directory(job_id)
    path = directory / "narration.wav"

    if not path.is_file():
        raise HTTPException(
            status_code=404, detail="Audio not found"
        )

    return FileResponse(
        path,
        media_type="audio/wav",
        filename=f"{job_id}.wav",
    )


@router.get("/{job_id}/captions")
def download_voice_captions(job_id: str):
    directory = get_voice_job_directory(job_id)
    path = directory / "captions.json"

    if not path.is_file():
        raise HTTPException(
            status_code=404, detail="Captions not found"
        )

    return FileResponse(
        path,
        media_type="application/json",
        filename=f"{job_id}-captions.json",
    )
