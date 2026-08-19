import uuid
from datetime import datetime
from pydantic import BaseModel

class EmployeeDashboardResponse(BaseModel):
    current_score: int
    status: str

class EmployeeHistoryResponse(BaseModel):
    log_id: uuid.UUID
    score_before: int
    score_after: int
    timestamp: datetime

    class Config:
        from_attributes = True

class EmployeeLogDetailResponse(BaseModel):
    log_id: uuid.UUID
    score_before: int
    score_after: int
    timestamp: datetime
    cause_of_change: str

    class Config:
        from_attributes = True
