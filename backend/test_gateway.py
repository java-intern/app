import asyncio
import sys
import uuid
import jwt
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.schemas.auth import AdminRegisterRequest, EmployeeRegisterRequest, LoginRequest
from app.utils.security import hash_password, verify_password, create_access_token, ITERATIONS
from app.models import Company, User, UserRole, TrustLog
from app.config import settings

# Mock cache layer to avoid needing a live Redis server
from app.api.auth import register_admin, register_employee, login
import app.api.auth
cached_data = {}
async def mock_cache_trust_score(user_id, current_score, status):
    cached_data[str(user_id)] = {"score": current_score, "status": status}

app.api.auth.cache_trust_score = mock_cache_trust_score

async def run_tests():
    print("=== STARTING GATEWAY VALIDATION ===")
    
    # 1. Verify Password Hashing Configuration
    print("\n[TEST 1] Verifying Password Hashing Configuration...")
    assert ITERATIONS == 600000, f"Expected 600000 iterations, got {ITERATIONS}"
    print(f"[SUCCESS] Confirmed PBKDF2 iterations = {ITERATIONS}")
    
    password = "SecurePassword123!"
    hashed = hash_password(password)
    print("[SUCCESS] Password hashed successfully.")
    assert hashed != password, "Hash must not equal plain password"
    assert verify_password(password, hashed), "Password verification failed"
    assert not verify_password("wrong_password", hashed), "Password verification allowed invalid password"
    print("[SUCCESS] Password verification and hashing integrity verified.")

    # 2. Verify JWT Token Generation & Claims
    print("\n[TEST 2] Verifying JWT Token Generation & Claims...")
    user_id = uuid.uuid4()
    company_id = uuid.uuid4()
    role = "EMPLOYEE"
    
    token_data = {
        "sub": str(user_id),
        "company_id": str(company_id),
        "role": role
    }
    token = create_access_token(data=token_data)
    print("[SUCCESS] Token generated successfully.")
    
    decoded = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert decoded["sub"] == str(user_id), "Subject claim mismatch"
    assert decoded["company_id"] == str(company_id), "Company ID claim mismatch"
    assert decoded["role"] == role, "Role claim mismatch"
    assert "exp" in decoded, "Expiration claim missing"
    print("[SUCCESS] Token claims validated successfully.")

    # 3. Verify Admin Workspace Provisioning Logic
    print("\n[TEST 3] Verifying Admin Workspace Provisioning...")
    # Mock Database Session
    mock_db = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    # Simulate email & company name check returning nothing (available)
    async def mock_execute_admin(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result
    
    mock_db.execute = mock_execute_admin

    admin_payload = AdminRegisterRequest(
        email="owner@securecorp.com",
        password="AdminPassword123",
        full_name="Secure Owner",
        company_name="Secure Corp"
    )

    response = await register_admin(payload=admin_payload, db=mock_db)
    print("[SUCCESS] Admin route executed successfully.")
    assert response.admin.email == "owner@securecorp.com"
    assert response.admin.role == "ADMIN"
    assert len(response.company.company_code) == 8
    assert response.company.name == "Secure Corp"
    print(f"[SUCCESS] Provisioned company {response.company.name} with code: {response.company.company_code}")

    # 4. Verify Employee Registration & Verification Logic
    print("\n[TEST 4] Verifying Employee Registration and Cache Sync...")
    
    # Mock Company response
    mock_company = Company(
        id=uuid.uuid4(),
        name="Secure Corp",
        company_code="CODE1234",
        is_active=True
    )
    
    # We need database mock to return:
    # 1st call (check existing email): None
    # 2nd call (check company by code): mock_company
    async def mock_execute(statement):
        result = MagicMock()
        # Check if statement is checking users or companies
        str_stmt = str(statement)
        if "from users" in str_stmt.lower():
            result.scalar_one_or_none.return_value = None
        else:
            result.scalar_one_or_none.return_value = mock_company
        return result

    mock_db.execute = mock_execute

    employee_payload = EmployeeRegisterRequest(
        email="worker@securecorp.com",
        password="WorkerPassword123",
        full_name="Alice Worker",
        company_code="CODE1234"
    )

    emp_response = await register_employee(payload=employee_payload, db=mock_db)
    print("[SUCCESS] Employee route executed successfully.")
    assert emp_response.email == "worker@securecorp.com"
    assert emp_response.role == "EMPLOYEE"
    
    # Verify active Redis cache layer contains user trust score of 100 with ACTIVE status
    emp_id_str = str(emp_response.id)
    assert emp_id_str in cached_data, "Employee score not written to active cache"
    assert cached_data[emp_id_str]["score"] == 100
    assert cached_data[emp_id_str]["status"] == "ACTIVE"
    print("[SUCCESS] Cache layer updated using key user:{user_id}:trust_score with score=100 and status=ACTIVE.")
    
    print("\n=== ALL GATEWAY VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
