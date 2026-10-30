
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.product import Product
from app.services.creative import LANGUAGES, run_creative_pipeline


router = APIRouter(
    prefix="/creative",
    tags=["Creative Director (Phase 2)"],
)


class PreviewRequest(BaseModel):
    product_id: str = Field(examples=["LL-003"])
    language: str = Field(default="en", examples=["en"])


@router.post("/preview")
def preview(
    payload: PreviewRequest,
    db: Session = Depends(get_db),
):
    if payload.language not in LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Language must be one of {list(LANGUAGES)}",
        )

    product = db.get(Product, payload.product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    data = {
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

    try:
        result = run_creative_pipeline(
            data,
            payload.language,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Creative generation failed "
                f"({type(exc).__name__}); "
                "check server logs and Gemini access"
            ),
        ) from exc

    if not result["approved"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Brand validation failed after 3 attempts",
                "violations": result["violations"],
                "attempts": result["attempts"],
                "trace": result["trace"],
            },
        )

    return {
        "product_id": payload.product_id,
        "language": payload.language,
        **result,
        "video_generated": False,
    }


@router.get("/languages")
def languages():
    return LANGUAGES
