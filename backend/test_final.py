import asyncio
import sys
import uuid
import json
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Imports from app
from app.models import Company, User, UserRole, TrustLog, generate_company_code
from app.schemas.auth import AdminRegisterRequest, EmployeeRegisterRequest, LoginRequest
from app.schemas.telemetry import TelemetrySubmit
from app.schemas.admin import OverrideRequest
from app.schemas.employee import EmployeeLogDetailResponse
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user_claims,
    require_employee_role,
    require_admin_role,
    ITERATIONS,
)
from app.api.auth import register_admin, register_employee, login
from app.api.telemetry import submit_telemetry, telemetry_staging
from app.api.sync import broadcaster, sse_event_generator
from app.api.admin import (
    get_dashboard_summary,
    list_employees_by_status,
    get_employee_investigation_details,
    search_and_sort_employees,
    force_mfa_override,
    lock_account_override,
    boost_score_override,
)
from app.api.employee import get_personal_dashboard, get_personal_history, get_personal_log_detail
from app.config import settings

# ── Redis Cache Simulation ──────────────────────────────────────────────────
redis_db = {}

async def mock_hset(key, mapping=None, field=None, value=None):
    if key not in redis_db:
        redis_db[key] = {}
    if mapping:
        for k, v in mapping.items():
            redis_db[key][k] = str(v)
    elif field:
        redis_db[key][field] = str(value)

async def mock_hgetall(key):
    return redis_db.get(key, {})

async def mock_get(key):
    return redis_db.get(key)

async def mock_set(key, value, ex=None):
    redis_db[key] = value

async def mock_delete(key):
    if key in redis_db:
        del redis_db[key]

async def mock_scan_iter(match):
    prefix = match.replace("*", "")
    for k in list(redis_db.keys()):
        if k.startswith(prefix):
            yield k

# Inject Redis Mocks Globally
import app.cache
import app.api.auth
import app.api.telemetry
import app.api.admin
import app.api.employee

mock_redis_client = MagicMock()
mock_redis_client.hset = mock_hset
mock_redis_client.hgetall = mock_hgetall
mock_redis_client.get = mock_get
mock_redis_client.set = mock_set
mock_redis_client.delete = mock_delete
mock_redis_client.scan_iter = mock_scan_iter

app.cache.get_redis_client = lambda: mock_redis_client
app.api.admin.get_redis_client = lambda: mock_redis_client
app.api.auth.cache_trust_score = app.cache.cache_trust_score
app.api.telemetry.cache_trust_score = app.cache.cache_trust_score
app.api.admin.cache_trust_score = app.cache.cache_trust_score
app.api.employee.cache_trust_score = app.cache.cache_trust_score
app.api.employee.get_cached_trust_score = app.cache.get_cached_trust_score

# ── End-To-End Test Runner ───────────────────────────────────────────────────

async def run_integration_suite():
    print("=================================================================")
    print("    ADAPTIVETRUST MOBILE - SYSTEM COMPREHENSIVE INTEGRATION PASS ")
    print("=================================================================")

    # Setup Tenant and User identifiers
    company_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()
    employee_uuid = uuid.uuid4()
    company_code = "TESTCODE"

    # Mock DB Context
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    # ── PART 1 & 2: Database Schema & Auth Gateway ──────────────────────────
    print("\n[PART 1 & 2] Verifying Dual Registration and Hashing Iterations...")
    assert ITERATIONS == 600000, "Hashing must be exactly 600,000 iterations!"
    
    # Simulating DB checks: Email & Company names are available
    async def mock_execute_admin(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result
    mock_db.execute = mock_execute_admin

    admin_reg = AdminRegisterRequest(
        email="admin@tenant.com",
        password="SecureAdminPassword123!",
        full_name="Tenant Admin",
        company_name="SecureTenant Inc"
    )

    # Register Admin & Create Company
    admin_resp = await register_admin(payload=admin_reg, db=mock_db)
    assert admin_resp.admin.email == "admin@tenant.com"
    assert admin_resp.admin.role == "ADMIN"
    assert len(admin_resp.company.company_code) == 8
    assert admin_resp.company.is_active is True
    print(f"[SUCCESS] Provisioned company workspace '{admin_resp.company.name}' with code: {admin_resp.company.company_code}")

    # Register Employee with the company code
    mock_company = Company(
        id=company_uuid,
        name="SecureTenant Inc",
        company_code=company_code,
        is_active=True
    )
    
    async def mock_execute_employee_reg(statement):
        result = MagicMock()
        str_stmt = str(statement).lower()
        if "from users" in str_stmt:
            result.scalar_one_or_none.return_value = None
        else:
            result.scalar_one_or_none.return_value = mock_company
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_employee_reg)

    emp_reg = EmployeeRegisterRequest(
        email="worker@tenant.com",
        password="EmployeePassword123!",
        full_name="Alice Employee",
        company_code=company_code
    )

    emp_resp = await register_employee(payload=emp_reg, db=mock_db)
    assert emp_resp.email == "worker@tenant.com"
    assert emp_resp.role == "EMPLOYEE"
    
    # Assert initial Redis Cache mapping
    user_cache_key = f"user:{str(emp_resp.id)}:trust_score"
    assert user_cache_key in redis_db
    assert redis_db[user_cache_key]["current_score"] == "100"
    assert redis_db[user_cache_key]["status"] == "ACTIVE"
    print("[SUCCESS] Registered employee and initialized active Redis cache to 100/ACTIVE.")

    # ── PART 3 & 4: Ingestion Pipeline & Trust Score Evaluations ───────────
    print("\n[PART 3 & 4] Verifying Secured Ingestion, Haversine, and Device checks...")
    
    # Setup employee context in DB mock
    mock_employee_db = User(
        id=employee_uuid,
        company_id=company_uuid,
        email="worker@tenant.com",
        full_name="Alice Employee",
        role="EMPLOYEE",
        current_score=100,
        last_lat=37.7749,
        last_lon=-122.4194,
        last_seen_at=datetime.now(timezone.utc) - timedelta(hours=1),
        is_active=True
    )

    async def mock_execute_telemetry(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_employee_db
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_telemetry)

    # Claims payload derived from JWT authorization
    employee_claims = {
        "sub": str(employee_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }

    # Anomalous Ingestion: ROOTED device AND impossible travel (~4100 km NYC in 1 hour)
    telemetry_payload = TelemetrySubmit(
        lat=40.7128,
        lon=-74.0060,
        device_status="ROOTED",
        activity_type="ANOMALOUS_SYNC"
    )

    # Run ingestion loop
    ingestion_resp = await submit_telemetry(
        payload=telemetry_payload,
        claims=employee_claims,
        db=mock_db
    )
    
    assert ingestion_resp.status == "RECEIVED"
    # Expected calculations: Behavior=50, Device=60, Network=100
    # Score = 0.4*50 + 0.3*60 + 0.3*100 = 68 (status WARN)
    assert mock_employee_db.current_score == 68
    assert redis_db[f"user:{str(employee_uuid)}:trust_score"]["current_score"] == "68"
    assert redis_db[f"user:{str(employee_uuid)}:trust_score"]["status"] == "WARN"
    print("[SUCCESS] Dual anomalies processed correctly. Trust score dropped to 68 (WARN).")

    # ── PART 5: Real-Time Sync & Event Routing (SSE) ───────────────────────
    print("\n[PART 5] Verifying Event Broadcaster SSE streaming and keep-alive packets...")
    admin_company_id = str(company_uuid)
    admin_queue = broadcaster.connect(admin_company_id)
    assert admin_company_id in broadcaster.connections

    # Simulate another telemetry check-in triggering broadcast
    mock_employee_db.current_score = 92
    await submit_telemetry(
        payload=TelemetrySubmit(lat=37.7749, lon=-122.4194, device_status="SECURE", activity_type="CHECKIN"),
        claims=employee_claims,
        db=mock_db
    )
    
    # Assert broadcast payload is delivered
    assert not admin_queue.empty()
    sse_raw = await admin_queue.get()
    sse_data = json.loads(sse_raw[6:])
    print(f"DEBUG: sse_data is {sse_data}")
    assert sse_data["user_id"] == str(employee_uuid)
    assert sse_data["current_score"] in (100, 80)
    assert sse_data["status"] == "ACTIVE"
    print("[SUCCESS] Telemetry log updates successfully broadcasted to company admin stream queue.")
    
    # Test keep-alive
    generator = sse_event_generator("empty-company-room")
    keep_alive_msg = await generator.__anext__()
    assert keep_alive_msg == ": keep-alive\n\n"
    print("[SUCCESS] Long-lived connections successfully receive keep-alive packets on timeouts.")

    # ── PART 6 & 7: Admin Control Monitor, Search Sorting, and Overrides ─────
    print("\n[PART 6 & 7] Verifying Admin Dashboard summaries, Search, and Override overrides...")
    
    admin_claims = {
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    }

    # 1. Posture dashboard stats
    async def mock_execute_dashboard(statement):
        result = MagicMock()
        str_stmt = str(statement).lower()
        if "is_active = true" in str_stmt or "is_active = :is_active_1" in str_stmt:
            result.scalar.return_value = 1  # Active user
        elif "current_score < 70" in str_stmt or "current_score < :current_score_1" in str_stmt:
            result.scalar.return_value = 0  # No alert
        elif "companies" in str_stmt:
            company_mock = MagicMock()
            company_mock.company_code = "5M1QCGF4"
            result.scalar_one_or_none.return_value = company_mock
        else:
            result.scalar.return_value = 2  # Total users
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_dashboard)

    dashboard = await get_dashboard_summary(claims=admin_claims, db=mock_db)
    assert dashboard.total_users == 2
    assert dashboard.active_user_count == 1
    assert dashboard.risk_alerts_count == 0
    print("[SUCCESS] Dashboard totals computed successfully.")

    # 2. Sorting Search Route
    async def mock_execute_sort(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_employee_db]
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_sort)
    search_res = await search_and_sort_employees(role=None, sort_by="score_desc", claims=admin_claims, db=mock_db)
    assert len(search_res) == 1
    assert search_res[0].id == employee_uuid
    print("[SUCCESS] Search router successfully defaults to all users and sorts correctly.")

    # 3. Lock Override Kill Switch & Revocation Scan
    session_token_key = "session:user_token_123"
    redis_db[session_token_key] = json.dumps({"user_id": str(employee_uuid), "company_id": str(company_uuid)})
    
    async def mock_execute_override(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_employee_db
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_override)

    lock_payload = OverrideRequest(user_id=employee_uuid)
    lock_resp = await lock_account_override(payload=lock_payload, claims=admin_claims, db=mock_db)
    assert lock_resp.status == "SUCCESS"
    assert mock_employee_db.current_score == 0
    assert redis_db[f"user:{str(employee_uuid)}:trust_score"]["status"] == "SUSPENDED"
    assert session_token_key not in redis_db, "Token was not deleted from active session cache!"
    print("[SUCCESS] Lock override sets score to 0, status to SUSPENDED, and revokes all user active sessions.")

    # 4. Boost Override and Telemetry Normalization
    mock_employee_db.current_score = 0
    mock_employee_db.last_lat = 40.7128
    mock_employee_db.last_lon = -74.0060
    mock_employee_db.last_seen_at = datetime.now(timezone.utc)

    boost_resp = await boost_score_override(payload=lock_payload, claims=admin_claims, db=mock_db)
    assert boost_resp.status == "SUCCESS"
    assert mock_employee_db.current_score == 100
    assert mock_employee_db.last_lat is None
    assert mock_employee_db.last_lon is None
    assert mock_employee_db.last_seen_at is None
    assert redis_db[f"user:{str(employee_uuid)}:trust_score"]["current_score"] == "100"
    assert redis_db[f"user:{str(employee_uuid)}:trust_score"]["status"] == "ACTIVE"
    print("[SUCCESS] Boost override manual reset normalizes score to 100 and clears historical telemetry bounds.")

    # ── PART 8 & 9: Employee Dashboard, History & Log Detail Transparency ──
    print("\n[PART 8 & 9] Verifying Employee Dashboard, History timeline, and Log Details...")
    
    # 1. Employee Dashboard Fallback (Redis cache hit)
    redis_db[f"user:{str(employee_uuid)}:trust_score"] = {"current_score": "100", "status": "ACTIVE"}
    mock_db.execute.reset_mock()
    emp_dash = await get_personal_dashboard(claims=employee_claims, db=mock_db)
    assert emp_dash.current_score == 100
    assert emp_dash.status == "ACTIVE"
    assert mock_db.execute.call_count == 0
    print("[SUCCESS] Employee dashboard served directly from active Redis cache.")

    # 2. Log detail sub-screen route ownership boundary checks
    log_detail = TrustLog(
        id=uuid.uuid4(),
        company_id=company_uuid,
        user_id=employee_uuid,
        score_before=92,
        score_after=68,
        cause_of_change="unexpected location change AND rooted device detection",
        created_at=datetime.now(timezone.utc)
    )

    async def mock_execute_log_detail(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = log_detail
        return result
    mock_db.execute = AsyncMock(side_effect=mock_execute_log_detail)

    # Retrieve valid log
    log_resp = await get_personal_log_detail(log_id=log_detail.id, claims=employee_claims, db=mock_db)
    assert log_resp.log_id == log_detail.id
    assert log_resp.score_before == 92
    assert log_resp.score_after == 68
    assert log_resp.cause_of_change == "unexpected location change AND rooted device detection"
    print("[SUCCESS] Transparency detail endpoint correctly displays historical penalty logs.")

    # Try lookup with mismatched user (ownership violation)
    other_emp_claims = {
        "sub": str(uuid.uuid4()), # Mismatch
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }
    try:
        await get_personal_log_detail(log_id=log_detail.id, claims=other_emp_claims, db=mock_db)
        assert False, "Mismatched user was allowed to read logs"
    except HTTPException as e:
        assert e.status_code == 404, f"Expected 404, got {e.status_code}"
        print("[SUCCESS] Security ownership bounds verified. Cross-user lookup attempts return 404 Not Found.")

    print("\n=================================================================")
    print("    ALL 9 PARTS COMPILATION AND INTEGRATION VERIFIED SUCCESSFULLY")
    print("=================================================================")

if __name__ == "__main__":
    asyncio.run(run_integration_suite())
