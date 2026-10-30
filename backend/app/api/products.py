from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import BACKEND_ROOT
from app.models.product import Product
from app.schemas import ProductOut, ProductCreate

router = APIRouter(prefix='/products', tags=['Products'])

@router.get('', response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db)):
    return db.scalars(select(Product).order_by(Product.id)).all()

@router.post('', response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    if db.get(Product, payload.id):
        raise HTTPException(409, 'Product ID already exists')
    product = Product(**payload.model_dump())
    db.add(product); db.commit(); db.refresh(product)
    return product

@router.get('/{product_id}', response_model=ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404, 'Product not found')
    return product

@router.get('/{product_id}/image')
def get_product_image(product_id: str, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404, 'Product not found')
    path = BACKEND_ROOT / 'data' / 'images' / f'{product_id}.png'
    if not path.is_file(): raise HTTPException(404, 'Image missing')
    return FileResponse(path, media_type='image/png')

@router.post('/{product_id}/images')
async def upload_product_image(product_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product: raise HTTPException(404, 'Product not found')
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024: raise HTTPException(413, 'Image too large (8 MB max)')
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(BytesIO(data)) as img:
            img.verify()
        with Image.open(BytesIO(data)) as img:
            if img.width * img.height > 25_000_000: raise HTTPException(413, 'Too many pixels')
            img.convert('RGB').save(BACKEND_ROOT / 'data' / 'images' / f'{product_id}.png')
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, 'Invalid image')
    product.image = f'images/{product_id}.png'; db.commit()
    return {'product_id': product_id, 'image': product.image}
