"""End-to-end video generation API."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product, VideoJob
from app.services.pipeline import run_video_pipeline


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pipeline",
    tags=["End-to-End Video Pipeline (Phase 5)"],
)


class PipelineRequest(BaseModel):
    product_id: str
    language: str = "en"
    voice: str = "Kore"


@router.post("/generate")
def generate_complete_video(
    payload: PipelineRequest,
    db: Session = Depends(get_db),
):
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

    job = VideoJob(
        id=str(uuid.uuid4()),
        product_id=product.id,
        status="processing",
    )

    db.add(job)
    db.commit()

    try:
        result = run_video_pipeline(
            product=product_data,
            language=payload.language,
            voice=payload.voice,
        )

        if result["status"] != "completed":
            job.status = "failed"
            db.commit()

            raise HTTPException(
                status_code=422,
                detail={
                    "message": result["error"],
                    "attempts": result["attempts"],
                    "trace": result["trace"],
                },
            )

        job.status = "completed"
        job.result_path = result["video"]["video_file"]
        db.commit()

        return {
            "job_id": job.id,
            "status": "completed",
            "product_id": product.id,
            "attempts": result["attempts"],
            "voice": result["voice"],
            "video": result["video"],
            "trace": result["trace"],
            "download_url": f"/render/{job.id}/video",
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Pipeline failed for job %s, product %s",
            job.id,
            product.id,
        )

        job.status = "failed"
        db.commit()

        raise HTTPException(
            status_code=502,
            detail=f"Pipeline failed: {type(exc).__name__}: {exc}",
        ) from exc