import socket
import logging
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

db_url = (settings.DATABASE_URL or "").strip()

# Normalize PostgreSQL URL scheme for asyncpg
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Localhost PostgreSQL check: if localhost:5432 is down, fallback to local SQLite
is_sqlite = "sqlite" in db_url or not db_url

if "postgresql+asyncpg://postgres:postgres@localhost:5432" in db_url or "localhost:5432" in db_url:
    try:
        with socket.create_connection(("localhost", 5432), timeout=0.5):
            pass
    except Exception:
        logger.info("Local PostgreSQL not detected on localhost:5432. Falling back to local SQLite database.")
        db_url = "sqlite+aiosqlite:///./adaptivetrust.db"
        is_sqlite = True

if is_sqlite:
    if not db_url:
        db_url = "sqlite+aiosqlite:///./adaptivetrust.db"
    engine_kwargs = {"connect_args": {"check_same_thread": False}}
else:
    engine_kwargs = {
        "pool_size": 10,
        "max_overflow": 5,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }

logger.info(f"Initializing Async Database Engine: {db_url.split('@')[-1] if '@' in db_url else db_url}")

# Create Async Engine
engine = create_async_engine(
    db_url,
    **engine_kwargs
)

# Create Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Session dependency generator for FastAPI endpoints
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
