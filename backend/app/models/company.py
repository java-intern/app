import random
import string
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

def generate_company_code() -> str:
    """Generate a unique 8-character alphanumeric company registration code."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    company_code: Mapped[str] = mapped_column(String(12), unique=True, index=True, default=generate_company_code)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    users: Mapped[list["User"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    trust_logs: Mapped[list["TrustLog"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company name={self.name!r} code={self.company_code!r}>"
