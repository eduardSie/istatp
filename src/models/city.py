from typing import Optional, List
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, ForeignKey
from src.models.base import Base


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_id: Mapped[int] = mapped_column(Integer, ForeignKey("countries.id", ondelete="RESTRICT"), nullable=False)

    country: Mapped["Country"] = relationship("Country", back_populates="cities")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="city")