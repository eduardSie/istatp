import uuid
import logging
import os
import boto3
from botocore.client import Config
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

from fastapi import APIRouter, Depends, Form, File, UploadFile, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.core.auth import get_current_user, require_admin
from src.models.event import Event
from src.models.tag import EventTag
from src.models.audit_log import EventAuditLog
from src.models.user import User
from src.schemas.event_schema import EventOut, EventUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Events"])
ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

S3_ENDPOINT = os.getenv("S3_ENDPOINT")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION = os.getenv("S3_REGION", "eu-central-1")
S3_PUBLIC_BASE = os.getenv("S3_PUBLIC_BASE", "")


def get_s3_client():
    kwargs = dict(
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name=S3_REGION,
    )
    if S3_ENDPOINT:
        kwargs["endpoint_url"] = S3_ENDPOINT
    return boto3.client("s3", **kwargs)


def make_presigned_url(key: str, expires_in: int = 3600) -> str:
    if not key:
        return None
    if key.startswith("http"):
        return key
    if S3_PUBLIC_BASE:
        return f"{S3_PUBLIC_BASE.rstrip('/')}/{key.lstrip('/')}"
    try:
        s3 = get_s3_client()
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key.lstrip("/")},
            ExpiresIn=expires_in,
        )
    except Exception as e:
        logger.error(f"S3 presign error: {e}")
        return key


def _resolve_tags(events):
    """Populate tags field from event_tags relationship."""
    for ev in events if isinstance(events, list) else [events]:
        ev.tags = [et.tag for et in ev.event_tags]
        ev.image_url = make_presigned_url(ev.image_url)
    return events


# ─── PUBLIC ROUTES ────────────────────────────────────────────────

@router.get("/events", response_model=List[EventOut])
async def list_events(
    search: Optional[str] = Query(None, description="Filter by title/description"),
    city_id: Optional[int] = Query(None),
    organizer_id: Optional[str] = Query(None),
    is_online: Optional[bool] = Query(None),
    tag_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Public: View Event List with optional Search & Filter."""
    _city_id       = int(city_id)       if city_id       and city_id.strip()       else None
    _organizer_id  = int(organizer_id)  if organizer_id  and organizer_id.strip()  else None
    _tag_id        = int(tag_id)        if tag_id        and tag_id.strip()         else None
    _is_online     = True if is_online == "true" else (False if is_online == "false" else None)
    query = select(Event).options(
        selectinload(Event.event_tags).selectinload(EventTag.tag)
    )

    if search:
        query = query.where(
            Event.title.ilike(f"%{search}%") | Event.description.ilike(f"%{search}%")
        )
    if _city_id is not None:
        query = query.where(Event.city_id == _city_id)
    if _organizer_id is not None:
        query = query.where(Event.organizer_id == _organizer_id)
    if _is_online is not None:
        query = query.where(Event.is_online == _is_online)
    if _tag_id is not None:
        query = query.join(EventTag, Event.id == EventTag.event_id).where(EventTag.tag_id == _tag_id)

    result = await db.execute(query)
    events = result.scalars().all()
    _resolve_tags(list(events))
    return events


@router.get("/event/{event_id}", response_model=EventOut)
async def get_event(event_id: int, db: AsyncSession = Depends(get_db)):
    """Public: View Event Details."""
    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    _resolve_tags(event)
    return event


# ─── ADMIN ROUTES ─────────────────────────────────────────────────

@router.post("/event", response_model=EventOut, status_code=201)
async def create_event(
    title: str = Form(...),
    organizer_id: int = Form(...),
    date_start: datetime = Form(...),
    price: Decimal = Form(Decimal("0.00")),
    city_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    website_url: Optional[str] = Form(None),
    date_end: Optional[datetime] = Form(None),
    registration_deadline: Optional[datetime] = Form(None),
    location_address: Optional[str] = Form(None),
    is_online: bool = Form(False),
    tag_ids: Optional[str] = Form(None, description="Comma-separated tag IDs, e.g. '1,2,3'"),
    image: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Create Event."""
    event = Event(
        title=title,
        organizer_id=organizer_id,
        date_start=date_start,
        price=price,
        city_id=city_id,
        description=description,
        website_url=website_url,
        date_end=date_end,
        registration_deadline=registration_deadline,
        location_address=location_address,
        is_online=is_online,
    )

    s3_uploaded_key = None
    if image:
        if image.content_type not in ALLOWED:
            raise HTTPException(status_code=415, detail="Unsupported file type")
        ext = ALLOWED[image.content_type]
        filename = f"{uuid.uuid4()}.{ext}"
        key = f"uploads/{filename}"
        try:
            s3 = get_s3_client()
            s3.upload_fileobj(
                Fileobj=image.file,
                Bucket=S3_BUCKET,
                Key=key,
                ExtraArgs={"ContentType": image.content_type, "ACL": "public-read"},
            )
            s3_uploaded_key = key
            event.image_url = key
        except Exception as e:
            logger.error("Upload failed", exc_info=e)
            raise HTTPException(status_code=500, detail="Image upload failed")

    db.add(event)
    try:
        await db.flush() 

        if tag_ids:
            try:
                parsed_ids = [int(t.strip()) for t in tag_ids.split(",") if t.strip().isdigit()]
            except ValueError:
                parsed_ids = []
            for tid in parsed_ids:
                db.add(EventTag(event_id=event.id, tag_id=tid))

        await db.commit()
    except Exception as e:
        logger.error("DB Error", exc_info=e)
        if s3_uploaded_key:
            try:
                get_s3_client().delete_object(Bucket=S3_BUCKET, Key=s3_uploaded_key)
            except Exception:
                pass
        if "foreign key" in str(e).lower():
            raise HTTPException(status_code=400, detail="Invalid organizer_id, city_id, or tag_id.")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    result = await db.execute(
        select(Event)
        .where(Event.id == event.id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one()
    _resolve_tags(event)
    return event


@router.patch("/event/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int,
    payload: EventUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Edit Event (with audit log)."""
    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    update_data = payload.model_dump(exclude_unset=True, exclude={"tag_ids"})

    for field, new_val in update_data.items():
        old_val = getattr(event, field, None)
        if str(old_val) != str(new_val):
            db.add(EventAuditLog(
                event_id=event_id,
                changed_by=admin.id,
                changed_column=field,
                old_value=str(old_val),
                new_value=str(new_val),
            ))
        setattr(event, field, new_val)

    if payload.tag_ids is not None:
        await db.execute(
            EventTag.__table__.delete().where(EventTag.event_id == event_id)
        )
        for tid in payload.tag_ids:
            db.add(EventTag(event_id=event_id, tag_id=tid))

    event.updated_at = datetime.utcnow()
    await db.commit()

    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one()
    _resolve_tags(event)
    return event


@router.delete("/event/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin: Delete Event."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Not found")

    if event.image_url:
        try:
            get_s3_client().delete_object(Bucket=S3_BUCKET, Key=event.image_url)
        except Exception:
            pass

    await db.delete(event)
    await db.commit()
    return None