import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, UserRole
from app.utils.security import hash_password, verify_password, create_access_token
from app.api.auth import login, LoginRequest

async def test_super_admin_login():
    async with AsyncSessionLocal() as db:
        print("Testing direct Super Admin login logic...")
        payload = LoginRequest(email="yogaroh16@gmail.com", password="yoga2004")
        res = await login(payload, db)
        print(f"[SUCCESS] Issued Access Token: {res.access_token[:30]}...")

if __name__ == "__main__":
    asyncio.run(test_super_admin_login())
