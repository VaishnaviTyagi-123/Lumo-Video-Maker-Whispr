
"""Phase 4 video rendering API."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.product import Product, VideoJob
from app.services.creative import CreativePlan
from app.services.render import render_product_video


router = APIRouter(
    prefix="/render",
    tags=["Video Rendering (Phase 4)"],
)


class RenderRequest(BaseModel):
    product_id: str
    language: str = "en"
    voice_job_id: str
    plan: CreativePlan


def product_to_dict(product: Product) -> dict:
    return {
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


@router.post("/generate")
def generate_video(
    payload: RenderRequest,
    db: Session = Depends(get_db),
):
    product = db.get(Product, payload.product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    job = VideoJob(
        id=str(uuid.uuid4()),
        product_id=product.id,
        status="processing",
    )

    db.add(job)
    db.commit()

    try:
        result = render_product_video(
            product=product_to_dict(product),
            plan=payload.plan,
            language=payload.language,
            voice_job_id=payload.voice_job_id,
        )

        job.status = "completed"
        job.result_path = result["video_file"]
        db.commit()

        return {
            "job_id": job.id,
            "status": job.status,
            **result,
            "download_url": f"/render/{job.id}/video",
        }

    except (ValueError, FileNotFoundError) as exc:
        job.status = "failed"
        db.commit()

        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        job.status = "failed"
        db.commit()

        raise HTTPException(
            status_code=502,
            detail=(
                "Video rendering failed: "
                + str(exc)
            ),
        ) from exc


@router.get("/{job_id}")
def get_render_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    try:
        job_id = str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid render job ID",
        )

    job = db.get(VideoJob, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Render job not found",
        )

    return {
        "job_id": job.id,
        "product_id": job.product_id,
        "status": job.status,
        "result_path": job.result_path,
    }


@router.get("/{job_id}/video")
def download_video(
    job_id: str,
    db: Session = Depends(get_db),
):
    try:
        job_id = str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid render job ID",
        )

    job = db.get(VideoJob, job_id)

    if job is None or job.status != "completed":
        raise HTTPException(
            status_code=404,
            detail="Completed video not found",
        )

    # Resolve from the stored job ID, not an arbitrary URL path.
    if not job.result_path:
        raise HTTPException(
            status_code=404,
            detail="Video path missing",
        )

    from pathlib import Path

    video_path = Path(job.result_path).resolve()
    media_root = settings.media_root.resolve()

    if not video_path.is_relative_to(media_root):
        raise HTTPException(
            status_code=500,
            detail="Invalid stored video path",
        )

    if not video_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Video file missing",
        )

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"{job_id}.mp4",
    )
