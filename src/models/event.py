from datetime import datetime
from typing import Optional, List
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Text, Boolean, TIMESTAMP, Numeric, ForeignKey, func
from src.models.base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    organizer_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False)
    date_start: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))

    date_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    registration_deadline: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    city_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cities.id", ondelete="SET NULL"), nullable=True)
    location_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, onupdate=func.now(), nullable=True)

    organizer: Mapped["Organizer"] = relationship("Organizer", back_populates="events")
    city: Mapped[Optional["City"]] = relationship("City", back_populates="events")
    event_tags: Mapped[List["EventTag"]] = relationship("EventTag", back_populates="event", cascade="all, delete-orphan")
    bookmarks: Mapped[List["Bookmark"]] = relationship("Bookmark", back_populates="event", cascade="all, delete-orphan")
    audit_logs: Mapped[List["EventAuditLog"]] = relationship("EventAuditLog", back_populates="event", cascade="all, delete-orphan")