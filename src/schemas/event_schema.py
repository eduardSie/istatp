from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal

from src.schemas.tag_schema import TagOut


class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    organizer_id: int
    city_id: Optional[int] = None
    website_url: Optional[str] = None
    price: Decimal = Decimal("0.00")
    date_start: datetime
    date_end: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    location_address: Optional[str] = None
    is_online: bool = False


class EventCreate(EventBase):
    tag_ids: Optional[List[int]] = []


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    city_id: Optional[int] = None
    website_url: Optional[str] = None
    price: Optional[Decimal] = None
    date_start: Optional[datetime] = None
    date_end: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    location_address: Optional[str] = None
    is_online: Optional[bool] = None
    tag_ids: Optional[List[int]] = None


class EventOut(EventBase):
    id: int
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    tags: List[TagOut] = []

    class Config:
        from_attributes = True