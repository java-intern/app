from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.telemetry import router as telemetry_router
from app.api.sync import router as sync_router
from app.api.admin import router as admin_router
from app.api.employee import router as employee_router
from app.api.super_admin import router as super_admin_router, seed_super_admin_account
from app.database import engine
from app.cache import get_redis_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup tasks: Create database tables automatically & patch schema for missing columns
    from app.database import engine
    from app.models.base import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Automatic column migration for existing databases
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_email_verified BOOLEAN NOT NULL DEFAULT 0;"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN verification_code VARCHAR(6);"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN verification_expires_at TIMESTAMP;"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE users ALTER COLUMN company_id DROP NOT NULL;"))
        except Exception:
            pass

    # Provision Platform Super Admin Account (yogaroh16@gmail.com)
    await seed_super_admin_account()

    yield
    # Shutdown tasks (close connection pools)
    await engine.dispose()
    redis_client = get_redis_client()
    await redis_client.aclose()

app = FastAPI(
    title="AdaptiveTrust Multi-Tenant Zero Trust API",
    description="Backend gateway services for company tenant registration and secure authentication.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration allowing cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Explicit OPTIONS handler for browser CORS preflight requests
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return Response(status_code=200)

# Register authentication, telemetry, sync, admin, employee, and super-admin routes
app.include_router(auth_router, prefix="/api/v1")
app.include_router(telemetry_router, prefix="/api/v1")
app.include_router(sync_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(employee_router, prefix="/api/v1")
app.include_router(super_admin_router, prefix="/api/v1")

@app.get("/health", tags=["Health"])
def health_check():
    """Simple API status checks."""
    return {"status": "healthy", "service": "AdaptiveTrust Mobile Gateway"}