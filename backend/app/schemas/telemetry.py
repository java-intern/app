import uuid
from pydantic import BaseModel, Field

class TelemetrySubmit(BaseModel):
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    device_status: str = Field(..., min_length=1, description="Device status (e.g. SECURE, ROOTED)")
    activity_type: str = Field(..., min_length=1, description="Type of employee behavior/action")

class TelemetryResponse(BaseModel):
    status: str = "RECEIVED"
    user_id: uuid.UUID
    company_id: uuid.UUID
