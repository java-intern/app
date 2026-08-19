import asyncio
import sys
import uuid
import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.telemetry import TelemetrySubmit
from app.utils.security import (
    create_access_token,
    get_current_user_claims,
    require_employee_role,
)
from app.api.telemetry import submit_telemetry, telemetry_staging
from app.config import settings
from unittest.mock import AsyncMock, MagicMock
from app.models.user import User

# Mock active Redis cache updates
import app.api.telemetry
async def mock_cache_trust_score(user_id, current_score, status):
    pass
app.api.telemetry.cache_trust_score = mock_cache_trust_score

async def run_tests():
    print("=== STARTING LOG INGESTION & PIPELINE VALIDATION ===")

    user_id = uuid.uuid4()
    company_id = uuid.uuid4()

    # Create dummy tokens
    employee_token = create_access_token({
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "EMPLOYEE"
    })
    admin_token = create_access_token({
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "ADMIN"
    })
    invalid_token = "invalid.token.here"

    # 1. Test JWT Verification with Invalid Token
    print("\n[TEST 1] Testing JWT Verification with Invalid Token...")
    cred_invalid = HTTPAuthorizationCredentials(scheme="Bearer", credentials=invalid_token)
    try:
        get_current_user_claims(cred_invalid)
        assert False, "Invalid token did not raise 401 Unauthorized"
    except HTTPException as e:
        assert e.status_code == 401, f"Expected 401, got {e.status_code}"
        print("[SUCCESS] Invalid token correctly rejected with 401 Unauthorized.")

    # 2. Test JWT Verification with Valid Token
    print("\n[TEST 2] Testing JWT Verification with Valid Token...")
    cred_valid = HTTPAuthorizationCredentials(scheme="Bearer", credentials=employee_token)
    claims = get_current_user_claims(cred_valid)
    assert claims["sub"] == str(user_id), "Subject claim mismatch"
    assert claims["company_id"] == str(company_id), "Company ID claim mismatch"
    assert claims["role"] == "EMPLOYEE", "Role claim mismatch"
    print("[SUCCESS] Valid token correctly accepted and claims decoded.")

    # 3. Test Role Guard: Employee Role (Must succeed)
    print("\n[TEST 3] Testing Role Guard with Employee Claim...")
    try:
        emp_claims = require_employee_role(claims)
        assert emp_claims["role"] == "EMPLOYEE"
        print("[SUCCESS] Employee claims correctly accepted by role guard.")
    except HTTPException as e:
        assert False, f"Employee role rejected: {e.detail}"

    # 4. Test Role Guard: Admin Role (Must be blocked)
    print("\n[TEST 4] Testing Role Guard with Admin Claim...")
    admin_claims = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": "ADMIN"
    }
    try:
        require_employee_role(admin_claims)
        assert False, "Admin claims were not blocked by Employee Role Guard"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403, got {e.status_code}"
        print("[SUCCESS] Admin token blocked correctly with 403 Forbidden.")

    # 5. Test Telemetry Submission and Log Enrichment
    print("\n[TEST 5] Testing Telemetry Log Ingestion and Multi-Tenant Enrichment...")
    payload = TelemetrySubmit(
        lat=37.7749,
        lon=-122.4194,
        device_status="ROOTED",
        activity_type="DATA_EXFILTRATION_TEST"
    )

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    mock_user = User(
        id=user_id,
        company_id=company_id,
        email="john@securecorp.com",
        current_score=100,
        last_lat=None,
        last_lon=None,
        last_seen_at=None,
        full_name="John Doe",
        role="EMPLOYEE"
    )

    async def mock_execute(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_user
        return result

    mock_db.execute = mock_execute

    response = await submit_telemetry(payload=payload, claims=claims, db=mock_db)
    assert response.status == "RECEIVED", f"Expected status 'RECEIVED', got {response.status}"
    assert response.user_id == user_id, "User ID enrichment mismatch"
    assert response.company_id == company_id, "Company ID enrichment mismatch"
    print("[SUCCESS] Ingestion endpoint accepted request and enriched tenant claims correctly.")

    # 6. Verify Hot-Path In-memory Staging
    print("\n[TEST 6] Checking In-Memory Log Staging Queue...")
    assert len(telemetry_staging) > 0, "No records staged in memory queue"
    staged_log = telemetry_staging[-1]
    
    assert staged_log["user_id"] == str(user_id)
    assert staged_log["company_id"] == str(company_id)
    assert staged_log["lat"] == 37.7749
    assert staged_log["lon"] == -122.4194
    assert staged_log["device_status"] == "ROOTED", "Device status string was modified or missing"
    assert staged_log["activity_type"] == "DATA_EXFILTRATION_TEST"
    print("[SUCCESS] Enriched log successfully staged in-memory with 'device_status' string intact.")

    print("\n=== ALL LOG INGESTION VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
