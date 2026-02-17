from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, ForeignKey, String, Text, TIMESTAMP, func
from src.models.base import Base


class EventAuditLog(Base):
    __tablename__ = "event_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    changed_column: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_date: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    event: Mapped["Event"] = relationship("Event", back_populates="audit_logs")
    changed_by_user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")