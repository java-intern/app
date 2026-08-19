import os
from datetime import datetime, timedelta, timezone
import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

ITERATIONS = 600000
KEY_LEN = 32
SALT_LEN = 16

security_scheme = HTTPBearer()

def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with exactly 600,000 iterations."""
    salt = os.urandom(SALT_LEN)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LEN,
        salt=salt,
        iterations=ITERATIONS,
    )
    key = kdf.derive(password.encode("utf-8"))
    
    salt_hex = salt.hex()
    key_hex = key.hex()
    return f"{salt_hex}:{key_hex}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify standard PBKDF2-HMAC-SHA256 password hash."""
    try:
        salt_hex, key_hex = hashed_password.split(":")
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LEN,
            salt=salt,
            iterations=ITERATIONS,
        )
        actual_key = kdf.derive(plain_password.encode("utf-8"))
        return actual_key == expected_key
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a secure JWT access token embedding metadata."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def get_current_user_claims(credentials: HTTPAuthorizationCredentials = Depends(security_scheme)) -> dict:
    """Extract and verify JWT claims from Authorization Bearer token."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired. Please log in again."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token."
        )

def require_employee_role(claims: dict = Depends(get_current_user_claims)) -> dict:
    """Ensure the authenticated user claims verify the EMPLOYEE role."""
    role = claims.get("role")
    if role != "EMPLOYEE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to employees only."
        )
    return claims

def require_admin_role(claims: dict = Depends(get_current_user_claims)) -> dict:
    """Ensure the authenticated user claims verify the ADMIN or SUPER_ADMIN role."""
    role = claims.get("role")
    if role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to admins only."
        )
    return claims

def require_super_admin_role(claims: dict = Depends(get_current_user_claims)) -> dict:
    """Ensure the authenticated user claims verify the SUPER_ADMIN role."""
    role = claims.get("role")
    if role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted to Super Admins only."
        )
    return claims
