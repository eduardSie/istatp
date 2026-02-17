from datetime import datetime
from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, TIMESTAMP, func
from src.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())

    bookmarks: Mapped[List["Bookmark"]] = relationship("Bookmark", back_populates="user")
    audit_logs: Mapped[List["EventAuditLog"]] = relationship("EventAuditLog", back_populates="changed_by_user")