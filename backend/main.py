from pathlib import Path
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from db.database import engine, Base, run_startup_migrations
from auth.bootstrap import ensure_admin_account
from auth.routes import router as auth_router
from api.settings import router as settings_router
from api.chat import router as chat_router
from api.images import router as images_router
from api.logs import router as logs_router
from api.summaries import router as summaries_router
from api.specialists import router as specialists_router
from api.feedback import router as feedback_router
from api.intake import router as intake_router
from api.menu import router as menu_router
from api.analysis import router as analysis_router
from api.admin import router as admin_router
from services.telemetry_context import clear_request_scope, start_request_scope
from services.telemetry_service import classify_request_group, flush_request_scope

settings.validate_security_configuration()

# Create all tables
Base.metadata.create_all(bind=engine)
run_startup_migrations()
ensure_admin_account()

app = FastAPI(title=settings.APP_NAME, version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    if not settings.SECURITY_HEADERS_ENABLED:
        return response
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    response.headers["Content-Security-Policy"] = settings.SECURITY_CSP
    return response


@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    group = classify_request_group(request.url.path)
    skip_streaming_chat = request.url.path == "/api/chat" and request.method.upper() == "POST"
    started = time.perf_counter()
    status_code = 500
    if group and not skip_streaming_chat:
        start_request_scope(
            path=request.url.path,
            method=request.method,
            request_group=group,
        )
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        if group and not skip_streaming_chat:
            user_id = getattr(getattr(request, "state", None), "user_id", None)
            flush_request_scope(
                status_code=status_code,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                user_id=int(user_id) if isinstance(user_id, int) else None,
            )
        else:
            clear_request_scope()

# Routers
app.include_router(auth_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(images_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(summaries_router, prefix="/api")
app.include_router(specialists_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(intake_router, prefix="/api")
app.include_router(menu_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

# Serve frontend static files (in production)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}
