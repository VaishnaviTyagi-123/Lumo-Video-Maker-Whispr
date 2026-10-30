import json
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.product import Product
from app.core.config import BACKEND_ROOT

def seed_products(db: Session):
    records = json.loads((BACKEND_ROOT / 'data' / 'products.json').read_text(encoding='utf-8'))
    for item in records:
        if not db.get(Product, item['id']):
            db.add(Product(**item))
    db.commit()
