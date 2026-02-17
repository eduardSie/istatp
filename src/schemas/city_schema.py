from pydantic import BaseModel
from typing import Optional


class CityBase(BaseModel):
    name: str
    country_id: int


class CityCreate(CityBase):
    pass


class CityOut(CityBase):
    id: int

    class Config:
        from_attributes = True