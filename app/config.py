from functools import lru_cache
from pathlib import Path
import secrets
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / '.env'), extra='ignore')
    database_url: str = 'sqlite:///./data/again.db'
    jwt_secret: str = ''
    app_env: str = 'development'
    cors_origins: str = ''
    admin_username: str = ''
    admin_password: str = ''
    payment_secret: str = ''  # Razorpay API secret
    payment_key_id: str = ''
    payment_webhook_secret: str = ''
    access_minutes: int = 15
    session_days: int = 7
    @model_validator(mode='after')
    def secure(self):
        if self.app_env == 'production':
            if len(self.jwt_secret) < 32: raise ValueError('Production JWT_SECRET must contain at least 32 characters')
            if self.database_url.startswith('sqlite:'): raise ValueError('Production requires MySQL/MariaDB, not SQLite')
            if '*' in self.cors_origins: raise ValueError('Use explicit CORS origins')
        elif not self.jwt_secret:
            self.jwt_secret = secrets.token_urlsafe(48)
        return self

@lru_cache
def get_settings(): return Settings()
