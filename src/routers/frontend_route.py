"""
Frontend router — serves Jinja2 HTML pages.
Auth is stored in an HttpOnly cookie (JWT token).
"""
from __future__ import annotations

import logging
import os
import uuid
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List

import boto3
from botocore.client import Config
from fastapi import (
    APIRouter, Depends, Form, File, HTTPException,
    Query, Request, Response, UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.auth import hash_password, verify_password, create_access_token
from src.core.database import get_db
from src.models.audit_log import EventAuditLog
from src.models.bookmark import Bookmark
from src.models.city import City
from src.models.event import Event
from src.models.organizer import Organizer
from src.models.tag import EventTag, Tag
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

# ── Templates ──────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # src/
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ── JWT settings (mirrors auth.py) ────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM  = "HS256"
COOKIE_KEY = "access_token"

# ── S3 helpers (mirrors event_route.py) ───────────────────────────
S3_ENDPOINT   = os.getenv("S3_ENDPOINT")
S3_BUCKET     = os.getenv("S3_BUCKET")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_REGION     = os.getenv("S3_REGION", "eu-central-1")
S3_PUBLIC_BASE= os.getenv("S3_PUBLIC_BASE", "")
ALLOWED_IMG   = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _s3():
    kwargs = dict(
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name=S3_REGION,
    )
    if S3_ENDPOINT:  
        kwargs["endpoint_url"] = S3_ENDPOINT
    return boto3.client("s3", **kwargs)

def _presign(key: str) -> Optional[str]:
    if not key:
        return None
    if key.startswith("http"):
        return key
    if S3_PUBLIC_BASE:
        return f"{S3_PUBLIC_BASE.rstrip('/')}/{key.lstrip('/')}"
    try:
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key.lstrip("/")},
            ExpiresIn=3600,
        )
    except Exception as e:
        logger.error("S3 presign error: %s", e)
        return None



# ── Auth helpers ───────────────────────────────────────────────────
def _get_user_from_cookie(request: Request, db: AsyncSession) -> None:
    """Returns (user_id, role) from JWT cookie, or None."""
    token = request.cookies.get(COOKIE_KEY)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"]), payload.get("role", "user")
    except (JWTError, KeyError, ValueError):
        return None


async def get_current_user_cookie(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    info = _get_user_from_cookie(request, db)
    if not info:
        return None
    user_id, _ = info
    return await db.get(User, user_id)


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_KEY, token,
        httponly=True, samesite="lax",
        max_age=60 * 60 * 24,  
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_KEY)


def _require_admin(user: Optional[User]) -> None:
    if not user or user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _resolve_tags_and_images(events):
    """Hydrate .tags and .image_url on event instances."""
    if not isinstance(events, list):
        events = [events]
    for ev in events:
        ev.tags = [et.tag for et in ev.event_tags]
        ev.image_url = _presign(ev.image_url)
    return events


def _flash(request: Request, category: str, message: str):
    """Store flash message in session (via request.state)."""
    if not hasattr(request.state, "messages"):
        request.state.messages = []
    request.state.messages.append((category, message))


def _ctx(request: Request, user: Optional[User], **kwargs) -> dict:
    """Build base template context."""
    messages = getattr(request.state, "messages", [])
    return {"request": request, "user": user, "messages": messages, **kwargs}


# ═══════════════════════════════════════════════════════════════════
# PUBLIC PAGES
# ═══════════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def page_index(
    request: Request,
    search: Optional[str] = Query(None),
    is_online: Optional[str] = Query(None),
    organizer_id: Optional[str] = Query(None),
    tag_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _organizer_id = int(organizer_id) if organizer_id and organizer_id.strip() else None
    _tag_id = int(tag_id) if tag_id and tag_id.strip() else None
    query = select(Event).options(
        selectinload(Event.event_tags).selectinload(EventTag.tag)
    )
    if search:
        query = query.where(
            Event.title.ilike(f"%{search}%") | Event.description.ilike(f"%{search}%")
        )
    if is_online == "true":
        query = query.where(Event.is_online == True)
    elif is_online == "false":
        query = query.where(Event.is_online == False)
    if _organizer_id:
        query = query.where(Event.organizer_id == _organizer_id)
    if _tag_id:
        query = query.join(EventTag, Event.id == EventTag.event_id).where(EventTag.tag_id == _tag_id)

    query = query.order_by(Event.date_start.asc())
    events = (await db.execute(query)).scalars().all()
    _resolve_tags_and_images(list(events))

    organizers = (await db.execute(select(Organizer).order_by(Organizer.name))).scalars().all()
    tags       = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()

    total_events     = (await db.execute(select(func.count()).select_from(Event))).scalar()
    total_organizers = (await db.execute(select(func.count()).select_from(Organizer))).scalar()

    return templates.TemplateResponse("index.html", _ctx(
        request, user,
        events=events,
        organizers=organizers,
        tags=tags,
        search=search,
        is_online=is_online,
        organizer_id=_organizer_id,
        tag_id=_tag_id,
        total_events=total_events,
        total_organizers=total_organizers,
    ))


@router.get("/event/{event_id}", response_class=HTMLResponse)
async def page_event_detail(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    _resolve_tags_and_images(event)
    organizer = await db.get(Organizer, event.organizer_id)

    is_bookmarked = False
    if user:
        bm = (await db.execute(
            select(Bookmark).where(
                Bookmark.user_id == user.id, Bookmark.event_id == event_id
            )
        )).scalar_one_or_none()
        is_bookmarked = bm is not None

    return templates.TemplateResponse("event_detail.html", _ctx(
        request, user,
        event=event,
        organizer=organizer,
        is_bookmarked=is_bookmarked,
    ))


# ═══════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════

@router.get("/login", response_class=HTMLResponse)
async def page_login(
    request: Request,
    user: Optional[User] = Depends(get_current_user_cookie),
):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", _ctx(request, user))


@router.post("/login")
async def do_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", _ctx(
            request, None, error="Invalid email or password.", email=email
        ), status_code=400)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    response = RedirectResponse("/", status_code=302)
    _set_auth_cookie(response, token)
    return response


@router.get("/register", response_class=HTMLResponse)
async def page_register(
    request: Request,
    user: Optional[User] = Depends(get_current_user_cookie),
):
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("register.html", _ctx(request, user))


@router.post("/register")
async def do_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse("register.html", _ctx(
            request, None, error="Email already registered.", email=email
        ), status_code=400)

    new_user = User(email=email, password_hash=hash_password(password), role="user")
    db.add(new_user)
    await db.commit()

    token = create_access_token({"sub": str(new_user.id), "role": new_user.role})
    response = RedirectResponse("/", status_code=302)
    _set_auth_cookie(response, token)
    return response


@router.get("/logout")
async def do_logout():
    response = RedirectResponse("/", status_code=302)
    _clear_auth_cookie(response)
    return response


# ═══════════════════════════════════════════════════════════════════
# BOOKMARKS
# ═══════════════════════════════════════════════════════════════════

@router.get("/bookmarks", response_class=HTMLResponse)
async def page_bookmarks(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(Bookmark)
        .where(Bookmark.user_id == user.id)
        .options(
            selectinload(Bookmark.event)
            .selectinload(Event.event_tags)
            .selectinload(EventTag.tag)
        )
        .order_by(Bookmark.added_at.desc())
    )
    bookmarks = result.scalars().all()
    for bm in bookmarks:
        _resolve_tags_and_images(bm.event)

    return templates.TemplateResponse("bookmarks.html", _ctx(
        request, user, bookmarks=bookmarks
    ))


@router.post("/bookmarks/{event_id}")
async def add_bookmark(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse("/login", status_code=302)

    existing = (await db.execute(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.event_id == event_id)
    )).scalar_one_or_none()

    if not existing:
        db.add(Bookmark(user_id=user.id, event_id=event_id))
        await db.commit()

    return RedirectResponse(f"/event/{event_id}", status_code=302)


@router.post("/bookmarks/{event_id}/remove")
async def remove_bookmark(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    if not user:
        return RedirectResponse("/login", status_code=302)

    bm = (await db.execute(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.event_id == event_id)
    )).scalar_one_or_none()

    if bm:
        await db.delete(bm)
        await db.commit()

    ref = request.headers.get("referer", "/bookmarks")
    return RedirectResponse(ref, status_code=302)


# ═══════════════════════════════════════════════════════════════════
# ADMIN — Dashboard
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin", response_class=HTMLResponse)
async def page_admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    stats = {
        "events":     (await db.execute(select(func.count()).select_from(Event))).scalar(),
        "organizers": (await db.execute(select(func.count()).select_from(Organizer))).scalar(),
        "tags":       (await db.execute(select(func.count()).select_from(Tag))).scalar(),
        "users":      (await db.execute(select(func.count()).select_from(User))).scalar(),
    }
    return templates.TemplateResponse("admin/dashboard.html", _ctx(
        request, user, stats=stats, active="dashboard"
    ))


# ═══════════════════════════════════════════════════════════════════
# ADMIN — Events
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin/events", response_class=HTMLResponse)
async def page_admin_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    events = (await db.execute(
        select(Event)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
        .order_by(Event.id.desc())
    )).scalars().all()
    for ev in events:
        ev.tags = [et.tag for et in ev.event_tags]

    return templates.TemplateResponse("admin/events.html", _ctx(
        request, user, events=events, active="events"
    ))


@router.get("/admin/events/new", response_class=HTMLResponse)
async def page_admin_event_new(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    organizers = (await db.execute(select(Organizer).order_by(Organizer.name))).scalars().all()
    cities     = (await db.execute(select(City).order_by(City.name))).scalars().all()
    tags       = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()
    return templates.TemplateResponse("admin/event_form.html", _ctx(
        request, user, event=None,
        organizers=organizers, cities=cities, tags=tags
    ))


@router.post("/admin/events/new")
async def do_admin_event_create(
    request: Request,
    title: str = Form(...),
    organizer_id: int = Form(...),
    date_start: datetime = Form(...),
    date_end: Optional[datetime] = Form(None),
    registration_deadline: Optional[datetime] = Form(None),
    price: Decimal = Form(Decimal("0.00")),
    city_id: Optional[int] = Form(None),
    location_address: Optional[str] = Form(None),
    website_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_online: Optional[str] = Form(None),
    tag_ids: List[int] = Form([]),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)

    event = Event(
        title=title, organizer_id=organizer_id,
        date_start=date_start, date_end=date_end,
        registration_deadline=registration_deadline,
        price=price, city_id=city_id or None,
        location_address=location_address,
        website_url=website_url, description=description,
        is_online=(is_online == "true"),
    )

    s3_key = None
    if image and image.filename:
        if image.content_type not in ALLOWED_IMG:
            organizers = (await db.execute(select(Organizer))).scalars().all()
            cities     = (await db.execute(select(City))).scalars().all()
            tags       = (await db.execute(select(Tag))).scalars().all()
            return templates.TemplateResponse("admin/event_form.html", _ctx(
                request, user, event=None, error="Unsupported image type.",
                organizers=organizers, cities=cities, tags=tags
            ), status_code=400)

    contents = await image.read()
    if contents:
        ext = ALLOWED_IMG[image.content_type]
        s3_key = f"uploads/{uuid.uuid4()}.{ext}"
        try:
            _s3().upload_fileobj(
                io.BytesIO(contents),
                S3_BUCKET,
                s3_key,
                ExtraArgs={"ContentType": image.content_type}, 
            )
            event.image_url = s3_key
        except Exception as e:
            logger.error("S3 upload failed: %s", e)

    db.add(event)
    await db.flush()
    for tid in tag_ids:
        db.add(EventTag(event_id=event.id, tag_id=tid))
    await db.commit()

    return RedirectResponse("/admin/events", status_code=302)


@router.get("/admin/events/{event_id}/edit", response_class=HTMLResponse)
async def page_admin_event_edit(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404)

    event.tags = [et.tag for et in event.event_tags]
    event.image_url = _presign(event.image_url)

    organizers = (await db.execute(select(Organizer).order_by(Organizer.name))).scalars().all()
    cities     = (await db.execute(select(City).order_by(City.name))).scalars().all()
    tags       = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()

    return templates.TemplateResponse("admin/event_form.html", _ctx(
        request, user, event=event,
        organizers=organizers, cities=cities, tags=tags
    ))


@router.post("/admin/events/{event_id}/edit")
async def do_admin_event_edit(
    event_id: int,
    request: Request,
    title: str = Form(...),
    organizer_id: int = Form(...),
    date_start: datetime = Form(...),
    date_end: Optional[datetime] = Form(None),
    registration_deadline: Optional[datetime] = Form(None),
    price: Decimal = Form(Decimal("0.00")),
    city_id: Optional[int] = Form(None),
    location_address: Optional[str] = Form(None),
    website_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_online: Optional[str] = Form(None),
    tag_ids: List[int] = Form([]),
    image: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    result = await db.execute(
        select(Event)
        .where(Event.id == event_id)
        .options(selectinload(Event.event_tags).selectinload(EventTag.tag))
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404)

    updates = {
        "title": title, "organizer_id": organizer_id,
        "date_start": date_start, "date_end": date_end,
        "registration_deadline": registration_deadline,
        "price": price, "city_id": city_id or None,
        "location_address": location_address,
        "website_url": website_url, "description": description,
        "is_online": (is_online == "true"),
    }
    for field, new_val in updates.items():
        old_val = getattr(event, field, None)
        if str(old_val) != str(new_val):
            db.add(EventAuditLog(
                event_id=event_id, changed_by=user.id,
                changed_column=field, old_value=str(old_val), new_value=str(new_val),
            ))
        setattr(event, field, new_val)

    if image and image.filename:
        if image.content_type in ALLOWED_IMG:
            contents = await image.read()
            if contents:
                ext = ALLOWED_IMG[image.content_type]
                s3_key = f"uploads/{uuid.uuid4()}.{ext}"
                try:
                    _s3().upload_fileobj(
                        io.BytesIO(contents),
                        S3_BUCKET, s3_key,
                        ExtraArgs={"ContentType": image.content_type},
                    )
                    event.image_url = s3_key
                except Exception as e:
                    logger.error("S3 upload failed: %s", e)

    await db.execute(EventTag.__table__.delete().where(EventTag.event_id == event_id))
    for tid in tag_ids:
        db.add(EventTag(event_id=event_id, tag_id=tid))

    event.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return RedirectResponse("/admin/events", status_code=302)


@router.post("/admin/events/{event_id}/delete")
async def do_admin_event_delete(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    event = await db.get(Event, event_id)
    if event:
        if event.image_url:
            try:
                _s3().delete_object(Bucket=S3_BUCKET, Key=event.image_url)
            except Exception:
                pass
        await db.delete(event)
        await db.commit()
    return RedirectResponse("/admin/events", status_code=302)


# ═══════════════════════════════════════════════════════════════════
# ADMIN — Tags
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin/tags", response_class=HTMLResponse)
async def page_admin_tags(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    tags = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()
    return templates.TemplateResponse("admin/tags.html", _ctx(
        request, user, tags=tags, active="tags"
    ))


@router.post("/admin/tags")
async def do_admin_tag_create(
    request: Request,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    existing = (await db.execute(select(Tag).where(Tag.name == name))).scalar_one_or_none()
    if existing:
        tags = (await db.execute(select(Tag).order_by(Tag.name))).scalars().all()
        return templates.TemplateResponse("admin/tags.html", _ctx(
            request, user, tags=tags, error=f"Tag '{name}' already exists."
        ), status_code=400)
    db.add(Tag(name=name))
    await db.commit()
    return RedirectResponse("/admin/tags", status_code=302)


@router.post("/admin/tags/{tag_id}/delete")
async def do_admin_tag_delete(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    tag = await db.get(Tag, tag_id)
    if tag:
        await db.delete(tag)
        await db.commit()
    return RedirectResponse("/admin/tags", status_code=302)


# ═══════════════════════════════════════════════════════════════════
# ADMIN — Organizers
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin/organizers", response_class=HTMLResponse)
async def page_admin_organizers(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    organizers = (await db.execute(select(Organizer).order_by(Organizer.name))).scalars().all()
    return templates.TemplateResponse("admin/organizers.html", _ctx(
        request, user, organizers=organizers, active="organizers"
    ))


@router.post("/admin/organizers")
async def do_admin_organizer_create(
    request: Request,
    name: str = Form(...),
    website: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    existing = (await db.execute(select(Organizer).where(Organizer.name == name))).scalar_one_or_none()
    if existing:
        organizers = (await db.execute(select(Organizer).order_by(Organizer.name))).scalars().all()
        return templates.TemplateResponse("admin/organizers.html", _ctx(
            request, user, organizers=organizers, error=f"Organizer '{name}' already exists."
        ), status_code=400)
    db.add(Organizer(name=name, website=website or None, contact_email=contact_email or None, description=description or None))
    await db.commit()
    return RedirectResponse("/admin/organizers", status_code=302)


# ═══════════════════════════════════════════════════════════════════
# ADMIN — Audit Log
# ═══════════════════════════════════════════════════════════════════

@router.get("/admin/audit", response_class=HTMLResponse)
async def page_admin_audit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_cookie),
):
    _require_admin(user)
    logs = (await db.execute(
        select(EventAuditLog).order_by(EventAuditLog.change_date.desc()).limit(200)
    )).scalars().all()
    return templates.TemplateResponse("admin/audit.html", _ctx(
        request, user, logs=logs, active="audit"
    ))