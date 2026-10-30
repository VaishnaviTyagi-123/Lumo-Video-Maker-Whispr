
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.models.product import Product, VideoJob
from app.seed import seed_products
from app.api import products, brand, system, creative, voice
from app.api import render
from app.api import pipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_products(db)

    yield


app = FastAPI(
    title="Lumo Living AI Product Video Maker",
    version="0.2.0",
    description=(
        "Phase 2: LangGraph creative preview and brand validation. "
        "TTS and video rendering arrive in later phases."
    ),
    lifespan=lifespan,
)

app.include_router(system.router)
app.include_router(products.router)
app.include_router(brand.router)
app.include_router(creative.router)
app.include_router(voice.router)
app.include_router(render.router)
app.include_router(pipeline.router)