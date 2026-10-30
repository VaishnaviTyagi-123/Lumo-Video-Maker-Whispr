from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_ROOT / '.env'), extra='ignore')
    gemini_api_key: str | None = None
    gemini_script_model: str = 'gemini-2.5-flash'
    gemini_tts_model: str = 'gemini-2.5-flash-preview-tts'
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'data' / 'app.db').as_posix()}"
    media_root: Path = BACKEND_ROOT / 'data' / 'media'
    video_duration_seconds: int = 15
    video_width: int = 1080
    video_height: int = 1920

settings = Settings()
