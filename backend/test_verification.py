import asyncio
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.models import Company, User, UserRole
from app.schemas.auth import (
    AdminRegisterRequest,
    EmployeeRegisterRequest,
    LoginRequest,
    VerifyEmailRequest,
    ResendCodeRequest
)
from app.api.auth import (
    register_admin,
    register_employee,
    verify_email,
    resend_verification_code,
    login
)

async def test_email_verification_flow():
    from app.config import settings
    settings.BREVO_API_KEY = "test_brevo_key_for_verification"
    print("\n=======================================================")
    print(" [TEST] RUNNING EMAIL VERIFICATION & BREVO INTEGRATION TEST")
    print("=======================================================")

    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()

    # DB state tracking
    users_db = []
    companies_db = []

    # Mock execute for User and Company lookups
    async def mock_execute(stmt):
        stmt_str = str(stmt)
        res = MagicMock()
        
        # Check email lookup
        if "users.email =" in stmt_str or "WHERE users.email =" in stmt_str:
            email_val = None
            for param in getattr(stmt, "_where_criteria", []):
                if hasattr(param, "right") and hasattr(param.right, "value"):
                    email_val = param.right.value
            found = next((u for u in users_db if u.email == email_val), None)
            res.scalar_one_or_none = MagicMock(return_value=found)
        # Check company name/code lookup
        elif "companies.name =" in stmt_str or "companies.company_code =" in stmt_str:
            found = companies_db[0] if companies_db else None
            res.scalar_one_or_none = MagicMock(return_value=found)
        else:
            res.scalar_one_or_none = MagicMock(return_value=None)
        return res

    mock_db.execute = mock_execute

    def mock_add(obj):
        if isinstance(obj, User):
            users_db.append(obj)
        elif isinstance(obj, Company):
            companies_db.append(obj)

    mock_db.add = mock_add

    # 1. Test Admin Registration & OTP Generation
    print("\n[STEP 1] Testing Admin Registration with Email OTP Generation...")
    admin_req = AdminRegisterRequest(
        email="admin@testcorp.com",
        password="SecurePassword123!",
        full_name="Admin Test",
        company_name="TestCorp"
    )
    admin_res = await register_admin(admin_req, mock_db)
    assert len(users_db) == 1, "User should be registered in DB"
    user = users_db[0]
    assert user.is_email_verified is False, "New registered user must have is_email_verified = False"
    assert user.verification_code is not None, "Verification code must be generated"
    assert len(user.verification_code) == 6, "OTP code must be 6 digits"
    print(f"[SUCCESS] Admin registered. Generated OTP: {user.verification_code}")

    # 2. Test Login before verification (should fail with email_not_verified)
    print("\n[STEP 2] Testing Login Before Email Verification...")
    try:
        await login(LoginRequest(email="admin@testcorp.com", password="SecurePassword123!"), mock_db)
        assert False, "Login should have been blocked for unverified email!"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403 status code, got {e.status_code}"
        assert e.detail == "email_not_verified", f"Expected detail 'email_not_verified', got {e.detail}"
        print(f"[SUCCESS] Login successfully blocked with detail: '{e.detail}'")

    # 3. Test Verify Email with Invalid OTP
    print("\n[STEP 3] Testing Email Verification with Invalid OTP Code...")
    try:
        await verify_email(VerifyEmailRequest(email="admin@testcorp.com", code="000000"), mock_db)
        assert False, "Verification should fail with wrong OTP!"
    except HTTPException as e:
        assert e.status_code == 400, "Expected 400 Bad Request"
        print(f"[SUCCESS] Invalid OTP blocked: {e.detail}")

    # 4. Test Verify Email with Valid OTP
    print("\n[STEP 4] Testing Email Verification with Valid 6-Digit OTP Code...")
    otp = user.verification_code
    verify_res = await verify_email(VerifyEmailRequest(email="admin@testcorp.com", code=otp), mock_db)
    assert verify_res.is_email_verified is True, "is_email_verified should be True after verification"
    assert user.is_email_verified is True, "User model is_email_verified updated in DB"
    print(f"[SUCCESS] Email verified successfully: {verify_res.message}")

    # 5. Test Login after verification (should succeed and return token)
    print("\n[STEP 5] Testing Login After Successful Verification...")
    login_res = await login(LoginRequest(email="admin@testcorp.com", password="SecurePassword123!"), mock_db)
    assert login_res.access_token is not None, "Access token should be issued after verification"
    print(f"[SUCCESS] Login successful! Issued JWT access token.")

    # 6. Test Resend Code for Employee
    print("\n[STEP 6] Testing Employee Registration & OTP Resend...")
    emp_req = EmployeeRegisterRequest(
        email="employee@testcorp.com",
        password="EmpPassword123!",
        full_name="Employee Test",
        company_code="TESTCODE"
    )
    emp_res = await register_employee(emp_req, mock_db)
    emp_user = users_db[1]
    original_otp = emp_user.verification_code
    print(f"Initial Employee OTP: {original_otp}")

    resend_res = await resend_verification_code(ResendCodeRequest(email="employee@testcorp.com"), mock_db)
    new_otp = emp_user.verification_code
    assert new_otp != original_otp, "Resend code must generate a new OTP"
    print(f"[SUCCESS] Resent code successfully. New OTP: {new_otp}")

    print("\n=======================================================")
    print(" ALL EMAIL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(test_email_verification_flow())
