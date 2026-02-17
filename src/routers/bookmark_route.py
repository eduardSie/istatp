from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.core.auth import get_current_user
from src.models.bookmark import Bookmark
from src.models.event import Event
from src.models.tag import EventTag
from src.models.user import User
from src.schemas.bookmark_schema import BookmarkOut

router = APIRouter(prefix="/api/v1/bookmarks", tags=["Bookmarks"])


@router.get("", response_model=List[BookmarkOut])
async def view_bookmarks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User: View Bookmarks."""
    result = await db.execute(
        select(Bookmark)
        .where(Bookmark.user_id == current_user.id)
        .options(
            selectinload(Bookmark.event)
            .selectinload(Event.event_tags)
            .selectinload(EventTag.tag)
        )
    )
    bookmarks = result.scalars().all()
    for bm in bookmarks:
        bm.event.tags = [et.tag for et in bm.event.event_tags]
    return bookmarks


@router.post("/{event_id}", status_code=201)
async def add_bookmark(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User: Add to Bookmarks."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    existing = (
        await db.execute(
            select(Bookmark).where(
                Bookmark.user_id == current_user.id, Bookmark.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Already bookmarked")

    db.add(Bookmark(user_id=current_user.id, event_id=event_id))
    await db.commit()
    return {"detail": "Bookmarked"}


@router.delete("/{event_id}", status_code=204)
async def remove_bookmark(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User: Remove from Bookmarks."""
    bm = (
        await db.execute(
            select(Bookmark).where(
                Bookmark.user_id == current_user.id, Bookmark.event_id == event_id
            )
        )
    ).scalar_one_or_none()
    if not bm:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    await db.delete(bm)
    await db.commit()
    return None