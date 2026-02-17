from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.auth import require_admin
from src.models.organizer import Organizer
from src.models.user import User
from src.schemas.organizer_schema import OrganizerCreate, OrganizerOut

router = APIRouter(prefix="/api/v1/organizers", tags=["Organizers"])


@router.get("", response_model=List[OrganizerOut])
async def list_organizers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Organizer))
    return result.scalars().all()


@router.get("/{organizer_id}", response_model=OrganizerOut)
async def get_organizer(organizer_id: int, db: AsyncSession = Depends(get_db)):
    org = await db.get(Organizer, organizer_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organizer not found")
    return org


@router.post("", response_model=OrganizerOut, status_code=201)
async def create_organizer(
    payload: OrganizerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    org = Organizer(**payload.model_dump())
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org