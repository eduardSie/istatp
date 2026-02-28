import asyncio
import os
import sys

sys.path.append(os.getcwd())

from sqlalchemy import select
from src.core.database import async_session, engine
from src.models.user import User
from src.core.auth import hash_password

async def create_first_admin():
    async with async_session() as db:
        email = "admin@admin.com"
        password = "admin_password"
        
        result = await db.execute(select(User).where(User.email == email))
        if result.scalar_one_or_none():
            return

        admin = User(
            email=email,
            password_hash=hash_password(password),
            role="admin"
        )
        db.add(admin)
        await db.commit()

if __name__ == "__main__":
    asyncio.run(create_first_admin())