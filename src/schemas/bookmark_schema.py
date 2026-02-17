from datetime import datetime
from pydantic import BaseModel

from src.schemas.event_schema import EventOut


class BookmarkOut(BaseModel):
    event_id: int
    added_at: datetime
    event: EventOut

    class Config:
        from_attributes = True