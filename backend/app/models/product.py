from sqlalchemy import String, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Product(Base):
    __tablename__ = 'products'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    features: Mapped[list] = mapped_column(JSON, nullable=False)
    sustainability: Mapped[str | None] = mapped_column(Text, nullable=True)
    image: Mapped[str] = mapped_column(String(200), nullable=False)

class VideoJob(Base):
    __tablename__ = 'video_jobs'
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey('products.id'))
    status: Mapped[str] = mapped_column(String(30), default='queued')
    result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
