from pydantic import BaseModel, EmailStr
from typing import Optional


class OrganizerBase(BaseModel):
    name: str
    website: Optional[str] = None
    contact_email: Optional[str] = None
    description: Optional[str] = None


class OrganizerCreate(OrganizerBase):
    pass


class OrganizerOut(OrganizerBase):
    id: int

    class Config:
        from_attributes = True