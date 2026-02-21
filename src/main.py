import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.routers import event_route
from src.routers import auth_route
from src.routers import bookmark_route
from src.routers import organizer_route
from src.routers import tag_route
from src.routers import audit_route
from src.routers import frontend_route

app = FastAPI(title="Professional Events Aggregator", version="1.0.0")

# ─── CORS ────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
)

# ─── STATIC FILES ─────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ─── FRONTEND PAGES────────────────────────────────────────────────
app.include_router(frontend_route.router)

# ─── REST API ROUTERS ─────────────────────────────────────────────
app.include_router(auth_route.router)
app.include_router(event_route.router)
app.include_router(bookmark_route.router)
app.include_router(organizer_route.router)
app.include_router(tag_route.router)
app.include_router(audit_route.router)