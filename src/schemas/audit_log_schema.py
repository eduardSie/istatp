from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class AuditLogOut(BaseModel):
    id: int
    event_id: int
    changed_by: Optional[int] = None
    changed_column: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    change_date: datetime

    class Config:
        from_attributes = True