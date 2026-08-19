import uuid
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db, AsyncSessionLocal
from app.models import User, Company, UserRole, TrustLog
from app.utils.security import require_super_admin_role, hash_password

router = APIRouter(prefix="/super-admin", tags=["Super Admin System Portal"])
logger = logging.getLogger(__name__)

SUPER_ADMIN_EMAIL = "yogaroh16@gmail.com"
SUPER_ADMIN_PASS = "yoga2004"

# ==========================================================================
# Automatic Seeder Function on Server Boot
# ==========================================================================
async def seed_super_admin_account():
    """Ensure the platform owner Super Admin account exists in DB."""
    async with AsyncSessionLocal() as db:
        try:
            stmt = select(User).where(User.email == SUPER_ADMIN_EMAIL)
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()
            
            hashed_pwd = hash_password(SUPER_ADMIN_PASS)
            
            if not existing:
                logger.info(f"Provisioning Platform Super Admin Account: {SUPER_ADMIN_EMAIL}")
                super_user = User(
                    id=uuid.uuid4(),
                    company_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
                    email=SUPER_ADMIN_EMAIL,
                    hashed_password=hashed_pwd,
                    role=UserRole.SUPER_ADMIN,
                    full_name="Platform Super Admin",
                    is_active=True,
                    is_email_verified=True,
                    current_score=100
                )
                db.add(super_user)
                await db.commit()
            else:
                # Update password hash if needed to guarantee login
                existing.hashed_password = hashed_pwd
                existing.role = UserRole.SUPER_ADMIN
                existing.is_email_verified = True
                existing.is_active = True
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to seed Super Admin account: {e}")

# ==========================================================================
# Super Admin Schemas
# ==========================================================================
class SuperAdminSummary(BaseModel):
    total_companies: int
    total_users: int
    total_employees: int
    total_admins: int
    average_trust_score: float
    verified_users_count: int

class CompanyOverviewItem(BaseModel):
    id: uuid.UUID
    name: str
    company_code: str
    is_active: bool
    total_employees: int
    admin_email: str | None
    created_at: datetime

    class Config:
        from_attributes = True

class UserOverviewItem(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str
    company_name: str
    is_active: bool
    is_email_verified: bool
    current_score: int
    status: str
    last_seen_at: datetime | None

    class Config:
        from_attributes = True

# ==========================================================================
# Super Admin Portal Routes
# ==========================================================================
@router.get("/summary", response_model=SuperAdminSummary)
async def get_system_summary(
    claims: dict = Depends(require_super_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """Global system-wide aggregates for Platform Super Admin."""
    # 1. Total companies count
    comp_res = await db.execute(select(func.count(Company.id)))
    total_companies = comp_res.scalar() or 0

    # 2. Total users count
    users_res = await db.execute(select(func.count(User.id)))
    total_users = users_res.scalar() or 0

    # 3. Employee & Admin Breakdown
    emp_res = await db.execute(select(func.count(User.id)).where(User.role == UserRole.EMPLOYEE))
    total_employees = emp_res.scalar() or 0

    admin_res = await db.execute(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
    total_admins = admin_res.scalar() or 0

    # 4. Verified Users count
    verified_res = await db.execute(select(func.count(User.id)).where(User.is_email_verified == True))
    verified_users_count = verified_res.scalar() or 0

    # 5. Global Avg Score
    avg_res = await db.execute(select(func.avg(User.current_score)).where(User.role == UserRole.EMPLOYEE))
    avg_score = avg_res.scalar() or 100.0

    return SuperAdminSummary(
        total_companies=total_companies,
        total_users=total_users,
        total_employees=total_employees,
        total_admins=total_admins,
        average_trust_score=round(avg_score, 1),
        verified_users_count=verified_users_count
    )

@router.get("/companies", response_model=list[CompanyOverviewItem])
async def list_all_registered_companies(
    claims: dict = Depends(require_super_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all company tenants registered on the platform with admin contact info."""
    comp_stmt = select(Company).order_by(Company.created_at.desc())
    comp_res = await db.execute(comp_stmt)
    companies = comp_res.scalars().all()

    result = []
    for c in companies:
        # Count employees in company
        count_stmt = select(func.count(User.id)).where(User.company_id == c.id)
        count_res = await db.execute(count_stmt)
        emp_count = count_res.scalar() or 0

        # Find Admin email
        admin_stmt = select(User.email).where(User.company_id == c.id, User.role == UserRole.ADMIN)
        admin_res = await db.execute(admin_stmt)
        admin_email = admin_res.scalar_one_or_none()

        result.append(CompanyOverviewItem(
            id=c.id,
            name=c.name,
            company_code=c.company_code,
            is_active=c.is_active,
            total_employees=emp_count,
            admin_email=admin_email,
            created_at=c.created_at
        ))

    return result

@router.get("/users", response_model=list[UserOverviewItem])
async def list_all_system_users(
    claims: dict = Depends(require_super_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """Retrieve all users across all corporate tenants for global system management."""
    users_stmt = select(User).order_by(User.created_at.desc())
    users_res = await db.execute(users_stmt)
    users = users_res.scalars().all()

    # Pre-fetch all companies to map names efficiently
    comp_res = await db.execute(select(Company))
    companies_dict = {c.id: c.name for c in comp_res.scalars().all()}

    result = []
    for u in users:
        c_name = companies_dict.get(u.company_id, "Platform System")
        u_status = "ACTIVE" if u.is_active else "SUSPENDED"
        if u.is_active:
            if u.current_score < 40:
                u_status = "RISK"
            elif u.current_score < 70:
                u_status = "WARN"

        result.append(UserOverviewItem(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role.value if hasattr(u.role, 'value') else str(u.role),
            company_name=c_name,
            is_active=u.is_active,
            is_email_verified=u.is_email_verified,
            current_score=u.current_score,
            status=u_status,
            last_seen_at=u.last_seen_at
        ))

    return result

@router.post("/company/{company_id}/toggle")
async def toggle_company_active_status(
    company_id: uuid.UUID,
    claims: dict = Depends(require_super_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """Enable or disable an entire company tenant workspace."""
    comp_stmt = select(Company).where(Company.id == company_id)
    comp_res = await db.execute(comp_stmt)
    company = comp_res.scalar_one_or_none()

    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company workspace not found.")

    company.is_active = not company.is_active
    await db.commit()

    return {"message": f"Company '{company.name}' active status changed to {company.is_active}.", "is_active": company.is_active}

@router.post("/user/{user_id}/force-otp")
async def super_admin_force_user_otp(
    user_id: uuid.UUID,
    claims: dict = Depends(require_super_admin_role),
    db: AsyncSession = Depends(get_db)
):
    """Platform Super Admin: Force 6-digit OTP verification & logout on any user."""
    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User account not found.")

    from app.api.auth import generate_otp
    from app.services.email import EmailService
    from datetime import timedelta

    otp_code = generate_otp()
    user.is_email_verified = False
    user.verification_code = otp_code
    user.verification_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

    await db.commit()
    await EmailService.send_verification_email(user.email, user.full_name, otp_code)

    return {"message": f"User '{user.email}' forced to verify with 6-digit OTP code.", "email": user.email}
