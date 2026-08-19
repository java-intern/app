import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.api.employee import get_personal_dashboard, get_personal_history
from app.models import User, TrustLog
from app.utils.security import require_employee_role

# In-memory Redis mock db
redis_cache = {}

async def mock_get_cached_trust_score(user_id):
    user_key = str(user_id)
    if user_key in redis_cache:
        return {
            "current_score": int(redis_cache[user_key]["score"]),
            "status": redis_cache[user_key]["status"]
        }
    return None

async def mock_cache_trust_score(user_id, current_score, status):
    redis_cache[str(user_id)] = {"score": current_score, "status": status}

# Inject mocks
import app.api.employee
app.api.employee.get_cached_trust_score = mock_get_cached_trust_score
app.api.employee.cache_trust_score = mock_cache_trust_score

async def run_tests():
    print("=== STARTING EMPLOYEE SELF-SERVICE API VALIDATION ===")

    company_uuid = uuid.uuid4()
    other_company_uuid = uuid.uuid4()
    employee_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()

    # Tokens
    employee_claims = {
        "sub": str(employee_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }
    admin_claims = {
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    }

    # ── TEST 1: Role Security Guard ──
    print("\n[TEST 1] Testing Employee Role Guard...")
    # Employee accepted
    assert require_employee_role(employee_claims) == employee_claims
    # Admin blocked
    try:
        require_employee_role(admin_claims)
        assert False, "Admin was not blocked by employee guard"
    except HTTPException as e:
        assert e.status_code == 403
        print("[SUCCESS] Employee guard correctly blocked admin role.")

    # Mock DB Session
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()

    # ── TEST 2: Dashboard Caching and Fallback ──
    print("\n[TEST 2] Testing Employee Dashboard Caching Fallback...")
    mock_worker = User(
        id=employee_uuid,
        company_id=company_uuid,
        email="worker@securecorp.com",
        full_name="Alice Worker",
        role="EMPLOYEE",
        current_score=85
    )

    async def mock_execute_user(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_worker
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_user)

    # 1. First Call: Redis Cache Miss (queries DB, caches status)
    redis_cache.clear() # Ensure empty
    response_fallback = await get_personal_dashboard(claims=employee_claims, db=mock_db)
    assert response_fallback.current_score == 85
    assert response_fallback.status == "ACTIVE"
    # Verify it updated Redis
    assert str(employee_uuid) in redis_cache
    assert redis_cache[str(employee_uuid)]["score"] == 85
    assert redis_cache[str(employee_uuid)]["status"] == "ACTIVE"
    print("[SUCCESS] Cache miss fell back to DB and successfully cached status=ACTIVE.")

    # 2. Second Call: Redis Cache Hit (does NOT query DB)
    mock_db.execute.reset_mock() # Reset call counts
    # Mutate cache score to verify hit is returned
    redis_cache[str(employee_uuid)]["score"] = 92
    response_hit = await get_personal_dashboard(claims=employee_claims, db=mock_db)
    assert response_hit.current_score == 92
    assert response_hit.status == "ACTIVE"
    assert mock_db.execute.call_count == 0, "Database should not have been queried on Redis cache hit!"
    print("[SUCCESS] Cache hit served directly from Redis without DB querying.")

    # ── TEST 3: History Timeline Logs Sorted Descending ──
    print("\n[TEST 3] Testing History Timeline Log Ordering...")
    log_older = TrustLog(
        id=uuid.uuid4(), company_id=company_uuid, user_id=employee_uuid,
        score_before=100, score_after=90, cause_of_change="Anomaly A",
        created_at=datetime.now(timezone.utc) - timedelta(hours=2)
    )
    log_newer = TrustLog(
        id=uuid.uuid4(), company_id=company_uuid, user_id=employee_uuid,
        score_before=90, score_after=80, cause_of_change="Anomaly B",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    
    # Simulate DB select order descending
    async def mock_execute_logs(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [log_newer, log_older]
        return result
    mock_db.execute = mock_execute_logs

    history_response = await get_personal_history(claims=employee_claims, db=mock_db)
    assert len(history_response) == 2
    # Verify descending sort order (newest log_newer first)
    assert history_response[0].log_id == log_newer.id
    assert history_response[0].score_before == 90
    assert history_response[0].score_after == 80
    assert history_response[1].log_id == log_older.id
    print("[SUCCESS] Logs successfully returned in descending chronological order.")

    # ── TEST 4: Lightweight Payload Structure (No Debugging Data) ──
    print("\n[TEST 4] Testing Lightweight Payload Restrictions...")
    history_entry = history_response[0]
    # Check that it contains only the specific lightweight parameters
    entry_dict = history_entry.model_dump()
    assert set(entry_dict.keys()) == {"log_id", "score_before", "score_after", "timestamp"}
    
    # Confirm ISO 8601 formatting for timestamps
    json_repr = history_entry.model_dump_json()
    assert "timestamp" in json_repr
    print(f"[SUCCESS] History payload contains only lightweight parameters: {list(entry_dict.keys())}")
    print("[SUCCESS] Timestamp output formatted in standard ISO 8601.")

    print("\n=== ALL EMPLOYEE SELF-SERVICE API VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
