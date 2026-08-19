import uuid
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models import User, TrustLog, UserRole, Company
from app.utils.security import require_admin_role
from app.schemas.admin import (
    DashboardResponse,
    EmployeeSummaryResponse,
    EmployeeDetailResponse,
    TrustLogHistoryResponse,
    OverrideRequest,
    OverrideResponse,
)
from app.cache import get_redis_client, get_trust_score_cache_key, cache_trust_score

router = APIRouter(prefix="/admin", tags=["Admin Control Panel"])

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard_summary(
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Posture Dashboard:
    Calculates corporate aggregates (total users, active user count, and risk alerts count)
    within the admin's company_id room. Returns zeroed values if no records exist.
    """
    company_id_str = claims["company_id"]
    company_uuid = uuid.UUID(company_id_str)

    # 1. Total users (admins + employees) in company
    total_stmt = select(func.count(User.id)).where(User.company_id == company_uuid)
    total_res = await db.execute(total_stmt)
    total_users = total_res.scalar() or 0

    # 2. Active users count
    active_stmt = select(func.count(User.id)).where(
        User.company_id == company_uuid,
        User.is_active == True
    )
    active_res = await db.execute(active_stmt)
    active_user_count = active_res.scalar() or 0

    # 3. Risk Alerts (employees with a trust score < 70)
    risk_stmt = select(func.count(User.id)).where(
        User.company_id == company_uuid,
        User.role == UserRole.EMPLOYEE,
        User.current_score < 70
    )
    risk_res = await db.execute(risk_stmt)
    risk_alerts_count = risk_res.scalar() or 0

    # 4. Fetch company invite code
    company_stmt = select(Company).where(Company.id == company_uuid)
    company_res = await db.execute(company_stmt)
    company = company_res.scalar_one_or_none()
    company_code = company.company_code if company else ""

    return DashboardResponse(
        total_users=total_users,
        active_user_count=active_user_count,
        risk_alerts_count=risk_alerts_count,
        company_code=company_code
    )

@router.get("/employees", response_model=list[EmployeeSummaryResponse])
async def list_employees_by_status(
    status_param: str = "ACTIVE",
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Employee Status Split:
    Returns employees matching requested is_active status.
    Returns empty list `[]` if no workers match.
    """
    company_id_str = claims["company_id"]
    company_uuid = uuid.UUID(company_id_str)

    # Map ACTIVE/INACTIVE params to boolean
    is_active_target = True
    if status_param.upper().strip() == "INACTIVE":
        is_active_target = False
    elif status_param.upper().strip() != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status parameter must be either ACTIVE or INACTIVE."
        )

    stmt = select(User).where(
        User.company_id == company_uuid,
        User.role == UserRole.EMPLOYEE,
        User.is_active == is_active_target
    )
    res = await db.execute(stmt)
    employees = res.scalars().all()

    # Returns empty array [] natively on no match
    return [EmployeeSummaryResponse.model_validate(emp) for emp in employees]

@router.get("/employees/search", response_model=list[EmployeeSummaryResponse])
async def search_and_sort_employees(
    role: str | None = None,
    sort_by: str = "score_desc",
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Advanced Sorting:
    Search/filter employees by role (optional), sorted by score (score_asc or score_desc),
    scoped within the admin's company tenant.
    """
    company_id_str = claims["company_id"]
    company_uuid = uuid.UUID(company_id_str)

    stmt = select(User).where(User.company_id == company_uuid)
    
    # Optional role filtering; if omitted, lists all users in the tenant
    if role:
        try:
            role_enum = UserRole[role.upper().strip()]
            stmt = stmt.where(User.role == role_enum)
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role parameter. Must be ADMIN or EMPLOYEE."
            )

    # Sort logic execution
    if sort_by == "score_asc":
        stmt = stmt.order_by(User.current_score.asc())
    elif sort_by == "score_desc":
        stmt = stmt.order_by(User.current_score.desc())
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort_by parameter. Must be score_asc or score_desc."
        )

    res = await db.execute(stmt)
    users = res.scalars().all()
    
    response_items = []
    for u in users:
        u_status = "ACTIVE" if u.is_active else "SUSPENDED"
        if u.is_active:
            if u.current_score < 40:
                u_status = "RISK"
            elif u.current_score < 70:
                u_status = "WARN"
        
        response_items.append(
            EmployeeSummaryResponse(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role.value if hasattr(u.role, 'value') else str(u.role),
                is_active=u.is_active,
                status=u_status,
                current_score=u.current_score,
                last_lat=u.last_lat,
                last_lon=u.last_lon,
                last_seen_at=u.last_seen_at
            )
        )
    return response_items

@router.get("/employees/{user_id}", response_model=EmployeeDetailResponse)
async def get_employee_investigation_details(
    user_id: uuid.UUID,
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Profile Investigation Detail:
    Verifies target user belongs to admin's company tenant, returning full details,
    location tracking, and trust logs sorted with newest events first (descending).
    """
    company_id_str = claims["company_id"]
    company_uuid = uuid.UUID(company_id_str)

    # 1. Fetch user and verify tenant bounds
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if not user or user.company_id != company_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found in your corporate workspace."
        )

    # 2. Fetch trust logs (strictly sorted with newest events first: descending)
    logs_stmt = select(TrustLog).where(TrustLog.user_id == user_id).order_by(TrustLog.created_at.desc())
    logs_res = await db.execute(logs_stmt)
    logs = logs_res.scalars().all()

    # Build response detail
    return EmployeeDetailResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value if hasattr(user.role, "value") else user.role,
        is_active=user.is_active,
        current_score=user.current_score,
        last_lat=user.last_lat,
        last_lon=user.last_lon,
        last_seen_at=user.last_seen_at,
        created_at=user.created_at,
        trust_logs=[TrustLogHistoryResponse.model_validate(log) for log in logs]
    )

@router.post("/override/mfa", response_model=OverrideResponse)
async def force_mfa_override(
    payload: OverrideRequest,
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Force MFA Override:
    Sets mfa_required flag to "true" in Redis active cache for the user.
    """
    company_uuid = uuid.UUID(claims["company_id"])
    
    stmt = select(User).where(User.id == payload.user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if not user or user.company_id != company_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in your company workspace."
        )
        
    client = get_redis_client()
    key = get_trust_score_cache_key(user.id)
    await client.hset(key, "mfa_required", "true")
    
    return OverrideResponse(status="SUCCESS", message="MFA requirement successfully enforced.")

@router.post("/override/lock", response_model=OverrideResponse)
async def lock_account_override(
    payload: OverrideRequest,
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Lock Account Kill Switch:
    Updates score to 0 and status to "SUSPENDED", logs override audit history,
    and revokes all active session tokens in Redis.
    """
    company_uuid = uuid.UUID(claims["company_id"])
    
    stmt = select(User).where(User.id == payload.user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if not user or user.company_id != company_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in your company workspace."
        )

    score_before = user.current_score
    user.current_score = 0
    
    # Audit log creation
    log = TrustLog(
        id=uuid.uuid4(),
        company_id=company_uuid,
        user_id=user.id,
        score_before=score_before,
        score_after=0,
        cause_of_change="Administrative account lock enforced"
    )
    db.add(log)
    
    # Cache sync (instant update before response)
    await cache_trust_score(user_id=user.id, current_score=0, status="SUSPENDED")
    
    # Scan and delete active session tokens mapping to this user
    client = get_redis_client()
    async for key in client.scan_iter("session:*"):
        val = await client.get(key)
        if val:
            try:
                session_data = json.loads(val)
                if session_data.get("user_id") == str(user.id):
                    await client.delete(key)
            except Exception:
                pass
                
    await db.commit()
    
    return OverrideResponse(status="SUCCESS", message="Account locked and all active sessions revoked.")

@router.post("/override/mfa", response_model=OverrideResponse)
async def force_otp_verification_override(
    payload: OverrideRequest,
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Force OTP Verification Override:
    Invalidates current session tokens, sets email verification to pending,
    generates a new 6-digit OTP, and sends verification email via Brevo.
    """
    company_uuid = uuid.UUID(claims["company_id"]) if claims.get("company_id") and claims.get("company_id") != "00000000-0000-0000-0000-000000000000" else None
    
    stmt = select(User).where(User.id == payload.user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if not user or (claims.get("role") != "SUPER_ADMIN" and company_uuid and user.company_id != company_uuid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee profile not found in your corporate workspace."
        )
    
    from app.api.auth import generate_otp
    from app.services.email import EmailService
    
    otp_code = generate_otp()
    user.is_email_verified = False
    user.verification_code = otp_code
    user.verification_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    # Revoke active session tokens
    client = get_redis_client()
    async for key in client.scan_iter("session:*"):
        val = await client.get(key)
        if val:
            try:
                session_data = json.loads(val)
                if session_data.get("user_id") == str(user.id):
                    await client.delete(key)
            except Exception:
                pass

    await db.commit()
    await EmailService.send_verification_email(user.email, user.full_name, otp_code)
    
    return OverrideResponse(status="SUCCESS", message=f"User {user.email} forced to logout and verify with 6-digit OTP email code.")

@router.post("/override/boost", response_model=OverrideResponse)
async def boost_score_override(
    payload: OverrideRequest,
    claims: dict = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Boost Score Override:
    Resets database trust score to 100, normalizes coordinates/timestamps
    to clear historical error states, and updates Redis active posture.
    """
    company_uuid = uuid.UUID(claims["company_id"])
    
    stmt = select(User).where(User.id == payload.user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    
    if not user or user.company_id != company_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found in your company workspace."
        )
        
    score_before = user.current_score
    user.current_score = 100
    
    # Safely normalize location telemetry to clear historical error states
    user.last_lat = None
    user.last_lon = None
    user.last_seen_at = None
    
    # Log audit entry
    log = TrustLog(
        id=uuid.uuid4(),
        company_id=company_uuid,
        user_id=user.id,
        score_before=score_before,
        score_after=100,
        cause_of_change="Manual administrative score restoration"
    )
    db.add(log)
    
    # Cache sync (instant update before response)
    await cache_trust_score(user_id=user.id, current_score=100, status="ACTIVE")
    
    await db.commit()
    
    return OverrideResponse(status="SUCCESS", message="Trust score manual restoration complete.")
