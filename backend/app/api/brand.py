from fastapi import APIRouter
from app.schemas import BrandGuideUpdate
from app.core.config import BACKEND_ROOT

router = APIRouter(prefix='/brand', tags=['Brand guide'])
GUIDE = BACKEND_ROOT / 'data' / 'brand-guide.md'

@router.get('/guide')
def get_guide():
    return {'brand': 'Lumo Living', 'content': GUIDE.read_text(encoding='utf-8')}

@router.put('/guide')
def update_guide(payload: BrandGuideUpdate):
    GUIDE.write_text(payload.content, encoding='utf-8')
    return {'updated': True, 'characters': len(payload.content)}
