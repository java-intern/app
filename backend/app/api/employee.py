import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, TrustLog
from app.utils.security import require_employee_role
from app.cache import get_cached_trust_score, cache_trust_score
from app.schemas.employee import EmployeeDashboardResponse, EmployeeHistoryResponse, EmployeeLogDetailResponse

router = APIRouter(prefix="/employee", tags=["Employee Self-Service"])
logger = logging.getLogger(__name__)

@router.get("/dashboard", response_model=EmployeeDashboardResponse)
async def get_personal_dashboard(
    claims: dict = Depends(require_employee_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Personal Dashboard:
    Pulls authenticated employee's trust score and status directly from Redis.
    Falls back to Postgres on cache miss and populates Redis instantly.
    """
    user_id_str = claims["sub"]
    user_uuid = uuid.UUID(user_id_str)

    # 1. Attempt to pull from fast-access Redis cache
    try:
        cached = await get_cached_trust_score(user_uuid)
        if cached:
            return EmployeeDashboardResponse(
                current_score=cached["current_score"],
                status=cached["status"]
            )
    except Exception as e:
        logger.error(f"Failed to read from Redis cache: {e}")

    # 2. Redis Cache Miss: Fall back to PostgreSQL database
    stmt = select(User).where(User.id == user_uuid)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found."
        )

    # Calculate status based on current score
    score = user.current_score
    if score >= 70:
        status_str = "ACTIVE"
    elif 40 <= score < 70:
        status_str = "WARN"
    else:
        status_str = "SUSPENDED"

    # Write to Redis active cache layer to handle future hits
    try:
        await cache_trust_score(user_id=user_uuid, current_score=score, status=status_str)
    except Exception as e:
        logger.error(f"Failed to write fallback to Redis cache: {e}")

    return EmployeeDashboardResponse(
        current_score=score,
        status=status_str
    )

@router.get("/history", response_model=list[EmployeeHistoryResponse])
async def get_personal_history(
    claims: dict = Depends(require_employee_role),
    db: AsyncSession = Depends(get_db)
):
    """
    History Timeline:
    Queries trust_logs matching user_id and company_id, sorted with newest first (descending).
    Outputs strictly lightweight log parameters (log_id, score_before, score_after, timestamp).
    """
    user_id_str = claims["sub"]
    company_id_str = claims["company_id"]

    user_uuid = uuid.UUID(user_id_str)
    company_uuid = uuid.UUID(company_id_str)

    stmt = select(TrustLog).where(
        TrustLog.user_id == user_uuid,
        TrustLog.company_id == company_uuid
    ).order_by(TrustLog.created_at.desc())

    res = await db.execute(stmt)
    logs = res.scalars().all()

    # Maps logs to response structure, avoiding any extra debug keys
    return [
        EmployeeHistoryResponse(
            log_id=log.id,
            score_before=log.score_before,
            score_after=log.score_after,
            timestamp=log.created_at
        )
        for log in logs
    ]

@router.get("/history/{log_id}", response_model=EmployeeLogDetailResponse)
async def get_personal_log_detail(
    log_id: uuid.UUID,
    claims: dict = Depends(require_employee_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Log Detail Sub-Screen:
    Returns the specific trust log details including 'cause_of_change' transparency.
    Strictly verifies ownership to prevent cross-user discovery scanning.
    """
    user_id_str = claims["sub"]
    company_id_str = claims["company_id"]

    user_uuid = uuid.UUID(user_id_str)
    company_uuid = uuid.UUID(company_id_str)

    stmt = select(TrustLog).where(TrustLog.id == log_id)
    res = await db.execute(stmt)
    log = res.scalar_one_or_none()

    # Strict boundary check: return 404 on mismatched owner or company to prevent scanning
    if not log or log.user_id != user_uuid or log.company_id != company_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log entry not found in your self-service portal."
        )

    return EmployeeLogDetailResponse(
        log_id=log.id,
        score_before=log.score_before,
        score_after=log.score_after,
        timestamp=log.created_at,
        cause_of_change=log.cause_of_change
    )
