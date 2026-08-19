import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/adaptivetrust")
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    JWT_SECRET_KEY: str = Field(default="replace_this_with_a_secure_random_key_in_production_32_chars_at_least")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Brevo Email Configuration
    BREVO_API_KEY: str | None = Field(default=None)
    BREVO_SENDER_EMAIL: str = Field(default="yoganandatamm@gmail.com")
    BREVO_SENDER_NAME: str = Field(default="AdaptiveTrust Security")

    # Pydantic Settings Config
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
