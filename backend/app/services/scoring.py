import math
from datetime import datetime
from app.models.user import User

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in kilometers."""
    R = 6371.0  # Earth radius in kilometers
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def evaluate_telemetry(
    user: User,
    current_lat: float,
    current_lon: float,
    device_status: str,
    current_time: datetime
) -> tuple[int, str, str]:
    """
    Evaluates telemetry against user's history using a weighted scoring formula:
    Score = (0.4 * Behavior) + (0.3 * Device) + (0.3 * Network)
    """
    behavior_score = 100
    device_score = 100
    network_score = 100
    
    penalties = []
    
    # 1. Behavior Penalty via Haversine distance
    if user.last_lat is not None and user.last_lon is not None and user.last_seen_at is not None:
        distance = haversine_distance(user.last_lat, user.last_lon, current_lat, current_lon)
        time_delta_seconds = (current_time - user.last_seen_at).total_seconds()
        time_delta_hours = time_delta_seconds / 3600.0
        
        # Guard against zero or negative time intervals
        if time_delta_hours > 0.000277:  # > 1 second
            speed = distance / time_delta_hours
            if speed > 900.0:
                behavior_score = max(0, behavior_score - 50)
                penalties.append("unexpected location change")
    
    # 2. Device Penalty
    if device_status.upper().strip() == "ROOTED":
        device_score = max(0, device_score - 40)
        penalties.append("rooted device detection")
        
    # Calculate final score: (0.4 * Behavior) + (0.3 * Device) + (0.3 * Network)
    final_score = int(round((0.4 * behavior_score) + (0.3 * device_score) + (0.3 * network_score)))
    final_score = max(0, min(100, final_score))
    
    # Determine status
    if final_score >= 70:
        status = "ACTIVE"
    elif 40 <= final_score < 70:
        status = "WARN"
    else:
        status = "SUSPENDED"
        
    # Generate stringed cause_of_change
    if penalties:
        penalties_str = " AND ".join(penalties)
        cause_of_change = f"Score dropped to {final_score} due to {penalties_str}"
    else:
        cause_of_change = f"Normal telemetry check-in. Trust score verified at {final_score}."
        
    return final_score, status, cause_of_change
