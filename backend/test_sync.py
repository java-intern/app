import asyncio
import sys
import uuid
import json
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.telemetry import TelemetrySubmit
from app.utils.security import (
    create_access_token,
    get_current_user_claims,
    require_admin_role,
)
from app.api.sync import broadcaster, sse_event_generator
from app.api.telemetry import submit_telemetry
from app.models.user import User

# Mock Redis cache layer to avoid needing a live Redis server
import app.api.telemetry
app.api.telemetry.cache_trust_score = AsyncMock()

async def run_tests():
    print("=== STARTING REAL-TIME EVENT SYNC & EVENT ROUTING VALIDATION ===")

    company_uuid = uuid.uuid4()
    other_company_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()
    employee_uuid = uuid.uuid4()

    # Generate test tokens
    admin_token = create_access_token({
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    })
    employee_token = create_access_token({
        "sub": str(employee_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    })
    invalid_token = "invalid.token.here"

    # ── TEST 1: Admin Authorization Guards ──
    print("\n[TEST 1] Testing Admin Authorization Guards on Stream...")
    
    # 1. No token (Invalid token logic)
    cred_invalid = HTTPAuthorizationCredentials(scheme="Bearer", credentials=invalid_token)
    try:
        get_current_user_claims(cred_invalid)
        assert False, "Invalid token allowed"
    except HTTPException as e:
        assert e.status_code == 401
        print("[SUCCESS] Missing/Invalid token blocked correctly.")

    # 2. Employee token (Blocked by Admin Guard)
    emp_claims = {
        "sub": str(employee_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }
    try:
        require_admin_role(emp_claims)
        assert False, "Employee was allowed to access admin stream"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403, got {e.status_code}"
        print("[SUCCESS] Employee token blocked correctly from admin stream.")

    # 3. Admin token (Allowed)
    admin_claims = {
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    }
    try:
        claims_out = require_admin_role(admin_claims)
        assert claims_out["role"] == "ADMIN"
        print("[SUCCESS] Admin token accepted by Admin Role guard.")
    except HTTPException as e:
        assert False, f"Admin token was rejected: {e.detail}"

    # ── TEST 2: Real-time Event Broadcast and Tenant Isolation ──
    print("\n[TEST 2] Testing Multi-Tenant Real-Time Broadcast Routing...")
    
    # Establish connection queue for Company A
    company_id_str = str(company_uuid)
    admin_queue = broadcaster.connect(company_id_str)
    assert company_id_str in broadcaster.connections
    print("[SUCCESS] Admin successfully subscribed to stream. Company room established.")

    # Setup Employee profile in DB mock
    mock_employee = User(
        id=employee_uuid,
        company_id=company_uuid,
        email="worker@company.com",
        full_name="Alice Worker",
        role="EMPLOYEE",
        current_score=100,
        last_lat=None,
        last_lon=None,
        last_seen_at=None
    )

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    
    async def mock_execute_telemetry(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_employee
        return result
    mock_db.execute = mock_execute_telemetry

    payload = TelemetrySubmit(
        lat=37.7749,
        lon=-122.4194,
        device_status="SECURE",
        activity_type="TELEMETRY_CHECKIN"
    )

    # Ingest telemetry (should trigger broadcast to company_id_str)
    await submit_telemetry(
        payload=payload,
        claims=emp_claims,
        db=mock_db
    )

    # Assert that admin_queue receives the payload
    assert not admin_queue.empty(), "Admin queue did not receive broadcasted event"
    raw_event = await admin_queue.get()
    
    # SSE data parsing
    assert raw_event.startswith("data: ")
    json_str = raw_event[6:].strip()
    event_data = json.loads(json_str)

    assert event_data["user_id"] == str(employee_uuid)
    assert event_data["name"] == "Alice Worker"
    assert event_data["role"] == "EMPLOYEE"
    assert event_data["location"]["lat"] == 37.7749
    assert event_data["location"]["lon"] == -122.4194
    assert event_data["current_score"] == 100
    assert event_data["status"] == "ACTIVE"
    assert "Normal telemetry check-in" in event_data["cause_of_change"]
    print("[SUCCESS] Broadcaster correctly routed detailed log data to admin room.")

    # ── TEST 3: Tenant Isolation Verification ──
    print("\n[TEST 3] Testing Multi-Tenant Data Isolation...")
    # Submit telemetry for Company B employee
    other_emp_uuid = uuid.uuid4()
    mock_other_employee = User(
        id=other_emp_uuid,
        company_id=other_company_uuid,
        email="other@company.com",
        full_name="Bob Worker",
        role="EMPLOYEE",
        current_score=100
    )
    
    async def mock_execute_other(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_other_employee
        return result
    mock_db.execute = mock_execute_other

    other_emp_claims = {
        "sub": str(other_emp_uuid),
        "company_id": str(other_company_uuid),
        "role": "EMPLOYEE"
    }

    await submit_telemetry(
        payload=payload,
        claims=other_emp_claims,
        db=mock_db
    )

    # Assert that Company A's admin queue did NOT receive this event
    assert admin_queue.empty(), "Admin queue received event belonging to a different tenant company!"
    print("[SUCCESS] Tenant data isolation verified. Telemetry events kept strictly partitioned.")

    # Disconnect admin queue
    broadcaster.disconnect(company_id_str, admin_queue)
    assert company_id_str not in broadcaster.connections
    print("[SUCCESS] Admin disconnected and room cleaned up successfully.")

    # ── TEST 4: SSE Keep-Alive Comments Verification ──
    print("\n[TEST 4] Testing SSE Long-Lived Stream Keep-Alive Formatting...")
    # Read from SSE generator with an empty queue to verify timeout behavior
    empty_company_id = "test-empty-company"
    generator = sse_event_generator(empty_company_id)
    
    # We will read exactly one event from the generator
    # Since generator timeout is 3.0s, this should return keep-alive
    keep_alive_event = await generator.__anext__()
    assert keep_alive_event == ": keep-alive\n\n", f"Expected keep-alive comment, got {keep_alive_event!r}"
    print("[SUCCESS] Generator correctly formats and yields keep-alive comments on timeout.")

    print("\n=== ALL REAL-TIME ROUTING & SYNC VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
