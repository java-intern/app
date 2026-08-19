import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

# Add current folder to sys.path
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.models.user import User
from app.services.scoring import evaluate_telemetry
from app.api.telemetry import submit_telemetry, telemetry_staging
from app.schemas.telemetry import TelemetrySubmit

# Setup local cache dictionary mock
import app.api.telemetry
cached_scores = {}
async def mock_cache_trust_score(user_id, current_score, status):
    cached_scores[str(user_id)] = {"score": current_score, "status": status}

app.api.telemetry.cache_trust_score = mock_cache_trust_score

async def run_tests():
    print("=== STARTING CORE TRUST SCORING ENGINE VALIDATION ===")

    user_uuid = uuid.uuid4()
    company_uuid = uuid.uuid4()
    
    # Base User mock instance
    base_user = User(
        id=user_uuid,
        company_id=company_uuid,
        email="john@securecorp.com",
        current_score=100,
        last_lat=None,
        last_lon=None,
        last_seen_at=None
    )

    # ── TEST 1: Baseline Check (No History, Secure Device) ──
    print("\n[TEST 1] Testing Baseline Ingestion (No History, Secure Device)...")
    now = datetime.now(timezone.utc)
    score, status, cause = evaluate_telemetry(
        user=base_user,
        current_lat=37.7749,
        current_lon=-122.4194,
        device_status="SECURE",
        current_time=now
    )
    assert score == 100, f"Expected 100, got {score}"
    assert status == "ACTIVE", f"Expected ACTIVE, got {status}"
    assert "Normal telemetry check-in" in cause
    print("[SUCCESS] Baseline score is 100 (ACTIVE) without history.")

    # ── TEST 2: Device Penalty Only (ROOTED Status) ──
    print("\n[TEST 2] Testing Device Penalty Only (ROOTED Status)...")
    score, status, cause = evaluate_telemetry(
        user=base_user,
        current_lat=37.7749,
        current_lon=-122.4194,
        device_status="ROOTED",
        current_time=now
    )
    # Expected: Behavior=100, Device=60, Network=100
    # Weighted Score: 0.4*100 + 0.3*60 + 0.3*100 = 40 + 18 + 30 = 88
    assert score == 88, f"Expected 88, got {score}"
    assert status == "ACTIVE", f"Expected ACTIVE, got {status}"
    assert "rooted device detection" in cause
    print("[SUCCESS] Device penalty calculated correctly: score=88 (ACTIVE).")

    # ── TEST 3: Impossible Travel Penalty Only (Speed > 900 km/h) ──
    print("\n[TEST 3] Testing Impossible Travel Penalty Only...")
    # Setup history: San Francisco (37.7749, -122.4194) 1 hour ago
    user_with_history = User(
        id=user_uuid,
        current_score=100,
        last_lat=37.7749,
        last_lon=-122.4194,
        last_seen_at=now - timedelta(hours=1)
    )
    # Current location: New York City (40.7128, -74.0060) (~4100 km away)
    # Speed is ~4100 km/h (>900 km/h)
    score, status, cause = evaluate_telemetry(
        user=user_with_history,
        current_lat=40.7128,
        current_lon=-74.0060,
        device_status="SECURE",
        current_time=now
    )
    # Expected: Behavior=50, Device=100, Network=100
    # Weighted Score: 0.4*50 + 0.3*100 + 0.3*100 = 20 + 30 + 30 = 80
    assert score == 80, f"Expected 80, got {score}"
    assert status == "ACTIVE", f"Expected ACTIVE, got {status}"
    assert "unexpected location change" in cause
    print("[SUCCESS] Impossible travel penalty calculated correctly: score=80 (ACTIVE).")

    # ── TEST 4: Combined Penalties (Impossible Travel AND Rooted) ──
    print("\n[TEST 4] Testing Combined Penalties...")
    score, status, cause = evaluate_telemetry(
        user=user_with_history,
        current_lat=40.7128,
        current_lon=-74.0060,
        device_status="ROOTED",
        current_time=now
    )
    # Expected: Behavior=50, Device=60, Network=100
    # Weighted Score: 0.4*50 + 0.3*60 + 0.3*100 = 20 + 18 + 30 = 68
    assert score == 68, f"Expected 68, got {score}"
    assert status == "WARN", f"Expected WARN, got {status}"
    assert "unexpected location change AND rooted device detection" in cause or "rooted device detection AND unexpected location change" in cause
    print(f"[SUCCESS] Combined penalties calculated correctly: score=68 (WARN).")
    print(f"[SUCCESS] Cause of change formatted correctly: '{cause}'.")

    # ── TEST 5: Router Integration with Database & Redis updates ──
    print("\n[TEST 5] Testing Telemetry Endpoint DB & Redis Cache updates...")
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    
    # Mock DB query returning our user instance using an explicit async function
    async def mock_execute_telemetry(statement):
        result = MagicMock()
        result.scalar_one_or_none.return_value = user_with_history
        return result
    
    mock_db.execute = mock_execute_telemetry

    claims = {
        "sub": str(user_uuid),
        "company_id": str(company_uuid),
        "role": "EMPLOYEE"
    }

    payload = TelemetrySubmit(
        lat=40.7128,
        lon=-74.0060,
        device_status="ROOTED",
        activity_type="ANOMALOUS_ACCESS"
    )

    response = await submit_telemetry(payload=payload, claims=claims, db=mock_db)
    
    assert response.status == "RECEIVED"
    
    # Check that database changes were captured
    assert user_with_history.current_score == 68
    assert user_with_history.last_lat == 40.7128
    assert user_with_history.last_lon == -74.0060
    assert mock_db.commit.call_count >= 1
    print("[SUCCESS] User model columns successfully updated and committed to database.")

    # Check that active Redis cache was updated instantly
    user_key = str(user_uuid)
    assert user_key in cached_scores
    assert cached_scores[user_key]["score"] == 68
    assert cached_scores[user_key]["status"] == "WARN"
    print("[SUCCESS] Redis cache key updated instantly with score=68 and status=WARN.")

    print("\n=== ALL SCORING ENGINE VALIDATIONS PASSED SUCCESSFULY ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
