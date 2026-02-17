from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional


class UserRegister(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"