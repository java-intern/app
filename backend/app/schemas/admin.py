import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr

class DashboardResponse(BaseModel):
    total_users: int
    active_user_count: int
    risk_alerts_count: int
    company_code: str

class EmployeeSummaryResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str = "EMPLOYEE"
    is_active: bool = True
    status: str = "ACTIVE"
    current_score: int = 100
    last_lat: float | None = None
    last_lon: float | None = None
    last_seen_at: datetime | None = None

    class Config:
        from_attributes = True

class TrustLogHistoryResponse(BaseModel):
    id: uuid.UUID
    score_before: int
    score_after: int
    cause_of_change: str
    created_at: datetime

    class Config:
        from_attributes = True

class EmployeeDetailResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    current_score: int
    last_lat: float | None
    last_lon: float | None
    last_seen_at: datetime | None
    created_at: datetime
    trust_logs: list[TrustLogHistoryResponse]

    class Config:
        from_attributes = True

class OverrideRequest(BaseModel):
    user_id: uuid.UUID

class OverrideResponse(BaseModel):
    status: str
    message: str
