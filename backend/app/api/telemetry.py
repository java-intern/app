import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, TrustLog
from app.schemas.telemetry import TelemetrySubmit, TelemetryResponse
from app.utils.security import require_employee_role
from app.services.scoring import evaluate_telemetry
from app.cache import cache_trust_score
from app.api.sync import broadcaster

router = APIRouter(prefix="/telemetry", tags=["Telemetry Log Ingestion"])
logger = logging.getLogger(__name__)

# Staging list for hot-path log ingestion (capped at 1000 to prevent memory leak)
telemetry_staging = deque(maxlen=1000)

@router.post("/submit", response_model=TelemetryResponse, status_code=status.HTTP_200_OK)
async def submit_telemetry(
    payload: TelemetrySubmit,
    claims: dict = Depends(require_employee_role),
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest validated telemetry log payload from employee client.
    Evaluates scoring anomalies, logs historical score transitions, and caches results.
    """
    user_id_str = claims["sub"]
    company_id_str = claims["company_id"]

    user_uuid = uuid.UUID(user_id_str)
    company_uuid = uuid.UUID(company_id_str)

    # 1. Fetch user from DB
    stmt = select(User).where(User.id == user_uuid)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authenticated user record not found."
        )

    current_time = datetime.now(timezone.utc)
    score_before = user.current_score

    # 2. Evaluate trust score using the scoring service
    score_after, status_str, cause = evaluate_telemetry(
        user=user,
        current_lat=payload.lat,
        current_lon=payload.lon,
        device_status=payload.device_status,
        current_time=current_time
    )

    # 3. Update User table details
    user.current_score = score_after
    user.last_lat = payload.lat
    user.last_lon = payload.lon
    user.last_seen_at = current_time

    # 4. Insert trust log row
    trust_log = TrustLog(
        id=uuid.uuid4(),
        company_id=company_uuid,
        user_id=user_uuid,
        score_before=score_before,
        score_after=score_after,
        cause_of_change=cause,
        created_at=current_time
    )
    db.add(trust_log)

    # 5. Populate Redis Active Cache Layer instantly before response returns
    try:
        await cache_trust_score(user_id=user_uuid, current_score=score_after, status=status_str)
    except Exception as e:
        logger.error(f"Failed to update active cache: {e}")

    # Commit changes to DB
    await db.commit()

    # 6. Broadcast event to company admins
    try:
        event_payload = {
            "user_id": user_id_str,
            "name": user.full_name,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "location": {
                "lat": payload.lat,
                "lon": payload.lon
            },
            "current_score": score_after,
            "status": status_str,
            "cause_of_change": cause
        }
        await broadcaster.broadcast(company_id_str, event_payload)
    except Exception as e:
        logger.error(f"Failed to broadcast real-time sync event: {e}")

    # Enrich details for the staging list
    enriched_log = {
        "user_id": user_id_str,
        "company_id": company_id_str,
        "lat": payload.lat,
        "lon": payload.lon,
        "device_status": payload.device_status,  # Preserved exactly as text
        "activity_type": payload.activity_type,
        "score_before": score_before,
        "score_after": score_after,
        "status": status_str,
        "cause_of_change": cause
    }

    # Hot path in-memory staging
    telemetry_staging.append(enriched_log)

    return TelemetryResponse(
        status="RECEIVED",
        user_id=user_uuid,
        company_id=company_uuid
    )
