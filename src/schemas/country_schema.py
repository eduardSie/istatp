from pydantic import BaseModel
from typing import Optional


class CountryBase(BaseModel):
    name: str
    iso_code: Optional[str] = None


class CountryCreate(CountryBase):
    pass


class CountryOut(CountryBase):
    id: int

    class Config:
        from_attributes = True