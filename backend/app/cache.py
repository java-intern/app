import json
import logging
import uuid
from typing import Any
import redis.asyncio as aioredis
import fakeredis.aioredis as fake_aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Initialize connection pool and client
redis_client: aioredis.Redis | None = None

def get_redis_client() -> aioredis.Redis:
    """Get or initialize the global async Redis client with FakeRedis fallback."""
    global redis_client
    if redis_client is None:
        url = settings.REDIS_URL
        if url and "redis" in url and "localhost" not in url:
            try:
                redis_client = aioredis.from_url(
                    url,
                    decode_responses=True,
                    socket_timeout=3.0
                )
                logger.info("Connected to remote Redis instance.")
            except Exception as e:
                logger.warning(f"Could not connect to Redis ({e}), using in-memory FakeRedis fallback.")
                redis_client = fake_aioredis.FakeRedis(decode_responses=True)
        else:
            # Fallback to FakeRedis for dev/standalone environments
            redis_client = fake_aioredis.FakeRedis(decode_responses=True)
    return redis_client

# ── Cache Key Helper Functions ───────────────────────────────────────────────

def get_tenant_cache_key(company_code: str) -> str:
    """Generate cache key for company codes."""
    return f"tenant:{company_code.upper().strip()}"

def get_session_cache_key(session_token: str) -> str:
    """Generate cache key for active sessions."""
    return f"session:{session_token.strip()}"

def get_trust_score_cache_key(user_id: uuid.UUID | str) -> str:
    """Generate cache key for a user's trust score."""
    return f"user:{str(user_id)}:trust_score"

# ── Tenant Active Cache Layer ──────────────────────────────────────────────────

async def cache_tenant(company_code: str, data: dict[str, Any], ttl: int = 3600) -> None:
    """Cache company details using company_code."""
    client = get_redis_client()
    key = get_tenant_cache_key(company_code)
    try:
        await client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        logger.error(f"Redis write error in cache_tenant: {e}")

async def get_cached_tenant(company_code: str) -> dict[str, Any] | None:
    """Retrieve company details from cache using company_code."""
    client = get_redis_client()
    key = get_tenant_cache_key(company_code)
    try:
        raw_val = await client.get(key)
        return json.loads(raw_val) if raw_val else None
    except Exception as e:
        logger.error(f"Redis read error in get_cached_tenant: {e}")
        return None

# ── User Session Active Cache Layer ─────────────────────────────────────────────

async def cache_session(session_token: str, data: dict[str, Any], ttl: int = 86400) -> None:
    """Cache active session details mapping to user_id, company_id and role."""
    client = get_redis_client()
    key = get_session_cache_key(session_token)
    try:
        await client.set(key, json.dumps(data), ex=ttl)
    except Exception as e:
        logger.error(f"Redis write error in cache_session: {e}")

async def get_cached_session(session_token: str) -> dict[str, Any] | None:
    """Retrieve session details from cache."""
    client = get_redis_client()
    key = get_session_cache_key(session_token)
    try:
        raw_val = await client.get(key)
        return json.loads(raw_val) if raw_val else None
    except Exception as e:
        logger.error(f"Redis read error in get_cached_session: {e}")
        return None

# ── Trust Score Active Cache Layer ──────────────────────────────────────────────

async def cache_trust_score(user_id: uuid.UUID | str, current_score: int, status: str) -> None:
    """Cache current user trust score details for rapid authentication/evaluation."""
    client = get_redis_client()
    key = get_trust_score_cache_key(user_id)
    try:
        await client.hset(
            key,
            mapping={
                "current_score": str(current_score),
                "status": status,
            }
        )
    except Exception as e:
        logger.error(f"Redis hset error in cache_trust_score: {e}")

async def get_cached_trust_score(user_id: uuid.UUID | str) -> dict[str, Any] | None:
    """Retrieve user trust score status from cache."""
    client = get_redis_client()
    key = get_trust_score_cache_key(user_id)
    try:
        val = await client.hgetall(key)
        if not val:
            return None
        return {
            "current_score": int(val["current_score"]),
            "status": val["status"],
        }
    except Exception as e:
        logger.error(f"Redis hgetall error in get_cached_trust_score: {e}")
        return None
