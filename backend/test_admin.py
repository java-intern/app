import asyncio
import sys
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.api.admin import (
    get_dashboard_summary,
    list_employees_by_status,
    get_employee_investigation_details,
)
from app.models import User, TrustLog, UserRole
from app.utils.security import require_admin_role

async def run_tests():
    print("=== STARTING ADMIN SCREENS & ACTIVE MONITOR VALIDATION ===")

    company_uuid = uuid.uuid4()
    other_company_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()
    employee_uuid = uuid.uuid4()

    # Admin claims context
    admin_claims = {
        "sub": str(admin_uuid),
        "company_id": str(company_uuid),
        "role": "ADMIN"
    }
    
    # Employee claims context
    emp_claims = {
        "sub": str(employee_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }

    # ── TEST 1: Admin Guard Verification ──
    print("\n[TEST 1] Testing Admin Guard Verification...")
    # Admin role is allowed
    assert require_admin_role(admin_claims) == admin_claims
    # Employee role is blocked with 403 Forbidden
    try:
        require_admin_role(emp_claims)
        assert False, "Employee was allowed to bypass admin guard"
    except HTTPException as e:
        assert e.status_code == 403
        print("[SUCCESS] Admin guard correctly blocks employee role.")

    # ── TEST 2: Dashboard Summary Calculations ──
    print("\n[TEST 2] Testing Posture Dashboard Summary Counters...")
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()

    # Simulate counts: Total users=10, Active users=8, Risk alerts=3
    async def mock_execute_counts(statement):
        result = MagicMock()
        str_stmt = str(statement).lower()
        if "is_active = true" in str_stmt or "is_active = :is_active_1" in str_stmt:
            result.scalar.return_value = 8
        elif "current_score < 70" in str_stmt or "current_score < :current_score_1" in str_stmt:
            result.scalar.return_value = 3
        elif "companies" in str_stmt:
            company_mock = MagicMock()
            company_mock.company_code = "CREDEUAT"
            result.scalar_one_or_none.return_value = company_mock
        else:
            result.scalar.return_value = 10
        return result
    
    mock_db.execute = mock_execute_counts

    dash_response = await get_dashboard_summary(claims=admin_claims, db=mock_db)
    assert dash_response.total_users == 10
    assert dash_response.active_user_count == 8
    assert dash_response.risk_alerts_count == 3
    print("[SUCCESS] Dashboard counts computed correctly: total=10, active=8, at-risk=3.")

    # ── TEST 3: Employees List - Empty State Verification ──
    print("\n[TEST 3] Testing Employees Directory Empty States...")
    # Simulate DB returning no matching records
    async def mock_execute_empty(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result
    
    mock_db.execute = mock_execute_empty
    
    # ACTIVE filter with no matches
    emp_list_empty = await list_employees_by_status(status_param="ACTIVE", claims=admin_claims, db=mock_db)
    assert emp_list_empty == [], f"Expected empty list [], got {emp_list_empty}"
    print("[SUCCESS] Empty directory filter correctly returns empty list `[]` without error.")

    # ── TEST 4: Employees List - Directory Filtering ──
    print("\n[TEST 4] Testing Employees Directory Filtering...")
    mock_worker = User(
        id=employee_uuid,
        company_id=company_uuid,
        email="worker@securecorp.com",
        full_name="Alice Worker",
        role="EMPLOYEE",
        is_active=True,
        current_score=92,
        created_at=datetime.now(timezone.utc)
    )
    
    async def mock_execute_list(statement):
        result = MagicMock()
        result.scalars.return_value.all.return_value = [mock_worker]
        return result
    
    mock_db.execute = mock_execute_list

    emp_list = await list_employees_by_status(status_param="ACTIVE", claims=admin_claims, db=mock_db)
    assert len(emp_list) == 1
    assert emp_list[0].id == employee_uuid
    assert emp_list[0].full_name == "Alice Worker"
    assert emp_list[0].current_score == 92
    print("[SUCCESS] Employees correctly listed and validated.")

    # ── TEST 5: Profile Detail Log Descending Order ──
    print("\n[TEST 5] Testing Profile Details and Log Ordering...")
    # Setup trust log history records
    log1 = TrustLog(id=uuid.uuid4(), score_before=100, score_after=88, cause_of_change="Anomaly A", created_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    log2 = TrustLog(id=uuid.uuid4(), score_before=88, score_after=68, cause_of_change="Anomaly B", created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    
    # We expect descending order (newest first, i.e., log2 then log1)
    mock_logs = [log2, log1]

    async def mock_execute_detail(statement):
        result = MagicMock()
        str_stmt = str(statement).lower()
        if "from users" in str_stmt:
            result.scalar_one_or_none.return_value = mock_worker
        else:
            result.scalars.return_value.all.return_value = mock_logs
        return result

    mock_db.execute = mock_execute_detail

    detail_res = await get_employee_investigation_details(user_id=employee_uuid, claims=admin_claims, db=mock_db)
    assert detail_res.id == employee_uuid
    assert detail_res.current_score == 92
    
    # Assert logs ordering (newest first)
    assert len(detail_res.trust_logs) == 2
    assert detail_res.trust_logs[0].cause_of_change == "Anomaly B"  # Created 5 mins ago (newest)
    assert detail_res.trust_logs[1].cause_of_change == "Anomaly A"  # Created 10 mins ago (older)
    print("[SUCCESS] Profile logs correctly sorted with newest events first (descending).")

    # ── TEST 6: Multi-Tenant Boundary Protection ──
    print("\n[TEST 6] Testing Multi-Tenant Boundary Protection...")
    # Simulate DB user belonging to another company
    mock_other_worker = User(
        id=employee_uuid,
        company_id=other_company_uuid,  # Mismatch
        email="other@corp.com",
        full_name="Bob Worker",
        role="EMPLOYEE",
        is_active=True,
        created_at=datetime.now(timezone.utc)
    )
    
    async def mock_execute_mismatch(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_other_worker
        return result
        
    mock_db.execute = mock_execute_mismatch

    try:
        await get_employee_investigation_details(user_id=employee_uuid, claims=admin_claims, db=mock_db)
        assert False, "Admin was allowed to inspect user from another company tenant"
    except HTTPException as e:
        assert e.status_code == 404
        print("[SUCCESS] Tenant isolation boundary enforced. Cross-tenant queries return 404.")

    print("\n=== ALL ADMIN DIRECTORY VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
