import uuid
from pydantic import BaseModel, EmailStr, Field

class AdminRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    company_name: str = Field(min_length=2, max_length=255)

class EmployeeRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    company_code: str = Field(min_length=8, max_length=12)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    status: str = "success"
    email: str | None = None
    message: str | None = None

class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    full_name: str | None
    is_email_verified: bool = False

    class Config:
        from_attributes = True

class CompanyResponse(BaseModel):
    id: uuid.UUID
    name: str
    company_code: str
    is_active: bool

    class Config:
        from_attributes = True

class AdminRegisterResponse(BaseModel):
    admin: UserResponse
    company: CompanyResponse

class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)

class VerifyLoginOTPRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)

class ResendCodeRequest(BaseModel):
    email: EmailStr

class VerifyEmailResponse(BaseModel):
    message: str
    email: EmailStr
    is_email_verified: bool
