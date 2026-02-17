from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.auth import require_admin
from src.models.audit_log import EventAuditLog
from src.models.user import User
from src.schemas.audit_log_schema import AuditLogOut

router = APIRouter(prefix="/api/v1/audit", tags=["Audit Log"])


@router.get("", response_model=List[AuditLogOut])
async def view_audit_log(
    event_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: View Audit Log."""
    query = select(EventAuditLog).order_by(EventAuditLog.change_date.desc())
    if event_id:
        query = query.where(EventAuditLog.event_id == event_id)

    result = await db.execute(query)
    return result.scalars().all()