from pydantic import BaseModel, ConfigDict, Field

class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    category: str
    description: str
    features: list[str]
    sustainability: str | None
    image: str

class ProductCreate(ProductOut):
    pass

class BrandGuideUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=30000)

class VideoSpec(BaseModel):
    duration_seconds: int = Field(default=15, ge=15, le=15)
    width: int = Field(default=1080, ge=1080, le=1080)
    height: int = Field(default=1920, ge=1920, le=1920)
