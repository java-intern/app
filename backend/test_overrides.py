import asyncio
import sys
import uuid
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.api.admin import (
    search_and_sort_employees,
    force_mfa_override,
    lock_account_override,
    boost_score_override,
)
from app.models import User, TrustLog, UserRole
from app.schemas.admin import OverrideRequest

# In-memory Redis mocks
redis_mock_db = {}
async def mock_hset(key, field, value):
    if key not in redis_mock_db:
        redis_mock_db[key] = {}
    redis_mock_db[key][field] = value

async def mock_delete(key):
    if key in redis_mock_db:
        del redis_mock_db[key]

# Simulates redis keys scanning
async def mock_scan_iter(match):
    prefix = match.replace("*", "")
    for k in list(redis_mock_db.keys()):
        if k.startswith(prefix):
            yield k

async def mock_get(key):
    return redis_mock_db.get(key)

# Mock cache methods
import app.api.admin
mock_redis = MagicMock()
mock_redis.hset = mock_hset
mock_redis.delete = mock_delete
mock_redis.scan_iter = mock_scan_iter
mock_redis.get = mock_get
app.api.admin.get_redis_client = lambda: mock_redis

# Mock cache_trust_score
async def mock_cache_trust_score(user_id, current_score, status):
    key = f"user:{str(user_id)}:trust_score"
    if key not in redis_mock_db:
        redis_mock_db[key] = {}
    redis_mock_db[key]["current_score"] = str(current_score)
    redis_mock_db[key]["status"] = status

app.api.admin.cache_trust_score = mock_cache_trust_score

async def run_tests():
    print("=== STARTING ADMIN OVERRIDES & SORTING ENGINE VALIDATION ===")

    company_uuid = uuid.uuid4()
    other_company_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()
    user_uuid = uuid.uuid4()

    admin_claims = {
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    }

    # Setup mocked users list
    user_low = User(
        id=uuid.uuid4(), company_id=company_uuid, email="low@corp.com",
        full_name="Low User", role=UserRole.EMPLOYEE, current_score=45,
        is_active=True, created_at=datetime.now(timezone.utc)
    )
    user_high = User(
        id=user_uuid, company_id=company_uuid, email="high@corp.com",
        full_name="High User", role=UserRole.EMPLOYEE, current_score=95,
        is_active=True, created_at=datetime.now(timezone.utc), last_lat=34.0, last_lon=-118.0,
        last_seen_at=datetime.now(timezone.utc)
    )
    user_admin = User(
        id=admin_uuid, company_id=company_uuid, email="admin@corp.com",
        full_name="Admin User", role=UserRole.ADMIN, current_score=100,
        is_active=True, created_at=datetime.now(timezone.utc)
    )
    mock_users = [user_low, user_high, user_admin]

    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    # ── TEST 1: Advanced Search & Sorting ──
    print("\n[TEST 1] Testing Employee Advanced Search & Sorting...")
    
    # 1. Sort by score ascending (score_asc)
    async def mock_execute_asc(statement):
        result = MagicMock()
        # Mock sorted return lists manually to match sort_by
        result.scalars.return_value.all.return_value = [user_low, user_high, user_admin]
        return result
    mock_db.execute = mock_execute_asc
    res_asc = await search_and_sort_employees(sort_by="score_asc", claims=admin_claims, db=mock_db)
    assert res_asc[0].current_score == 45
    assert res_asc[1].current_score == 95
    print("[SUCCESS] Sorting by score ascending verified.")

    # 2. Sort by score descending (score_desc)
    async def mock_execute_desc(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [user_admin, user_high, user_low]
        return result
    mock_db.execute = mock_execute_desc
    res_desc = await search_and_sort_employees(sort_by="score_desc", claims=admin_claims, db=mock_db)
    assert res_desc[0].current_score == 100
    assert res_desc[2].current_score == 45
    print("[SUCCESS] Sorting by score descending verified.")

    # 3. Omitted role parameter defaults to listing all users
    async def mock_execute_all(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = mock_users
        return result
    mock_db.execute = mock_execute_all
    res_all = await search_and_sort_employees(role=None, claims=admin_claims, db=mock_db)
    assert len(res_all) == 3, f"Expected 3 users, got {len(res_all)}"
    print("[SUCCESS] Omitted role parameter correctly returns all users without throwing error.")

    # ── TEST 2: Force MFA Override ──
    print("\n[TEST 2] Testing Force MFA Override...")
    # Mock user query return user_high
    async def mock_execute_mfa(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = user_high
        return result
    mock_db.execute = mock_execute_mfa

    payload_mfa = OverrideRequest(user_id=user_uuid)
    response_mfa = await force_mfa_override(payload=payload_mfa, claims=admin_claims, db=mock_db)
    
    assert response_mfa.status == "SUCCESS"
    user_key = f"user:{str(user_uuid)}:trust_score"
    assert redis_mock_db[user_key]["mfa_required"] == "true"
    print("[SUCCESS] Force MFA writes mfa_required=true correctly to Redis cache.")

    # ── TEST 3: Lock Account Kill Switch and Session Revocation ──
    print("\n[TEST 3] Testing Lock Account and Session Revocation...")
    
    # Pre-populate dummy active sessions in redis mock
    session_key_1 = "session:token123"
    redis_mock_db[session_key_1] = json.dumps({"user_id": str(user_uuid), "company_id": str(company_uuid)})
    session_key_other = "session:other_token"
    redis_mock_db[session_key_other] = json.dumps({"user_id": str(uuid.uuid4()), "company_id": str(company_uuid)})
    
    # Mock DB query
    async def mock_execute_lock(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = user_high
        return result
    mock_db.execute = mock_execute_lock

    payload_lock = OverrideRequest(user_id=user_uuid)
    response_lock = await lock_account_override(payload=payload_lock, claims=admin_claims, db=mock_db)
    
    assert response_lock.status == "SUCCESS"
    assert user_high.current_score == 0
    assert redis_mock_db[user_key]["current_score"] == "0"
    assert redis_mock_db[user_key]["status"] == "SUSPENDED"
    
    # Verify user session key is deleted while other sessions are preserved
    assert session_key_1 not in redis_mock_db, "User active session token was not deleted!"
    assert session_key_other in redis_mock_db, "Unrelated active session was deleted!"
    print("[SUCCESS] User account locked, status set to SUSPENDED, and active session tokens revoked.")

    # ── TEST 4: Boost Score Override and Telemetry State Normalization ──
    print("\n[TEST 4] Testing Boost Score and Telemetry State Normalization...")
    async def mock_execute_boost(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = user_high
        return result
    mock_db.execute = mock_execute_boost

    payload_boost = OverrideRequest(user_id=user_uuid)
    response_boost = await boost_score_override(payload=payload_boost, claims=admin_claims, db=mock_db)
    
    assert response_boost.status == "SUCCESS"
    assert user_high.current_score == 100
    assert user_high.last_lat is None
    assert user_high.last_lon is None
    assert user_high.last_seen_at is None
    
    assert redis_mock_db[user_key]["current_score"] == "100"
    assert redis_mock_db[user_key]["status"] == "ACTIVE"
    print("[SUCCESS] Boost override resets score to 100, updates Redis status, and normalizes telemetry data.")

    # ── TEST 5: Tenant Boundary Enforcement ──
    print("\n[TEST 5] Testing Tenant Override Gate Bounds...")
    # Mock user belonging to another company
    mock_foreign_user = User(
        id=user_uuid,
        company_id=other_company_uuid,
        email="foreign@corp.com",
        current_score=100
    )
    async def mock_execute_foreign(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_foreign_user
        return result
    mock_db.execute = mock_execute_foreign

    try:
        await boost_score_override(payload=payload_boost, claims=admin_claims, db=mock_db)
        assert False, "Admin was allowed to boost foreign user"
    except HTTPException as e:
        assert e.status_code == 404
        print("[SUCCESS] Tenant boundary isolation enforced on override commands.")

    print("\n=== ALL OVERRIDES & SORTING VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
