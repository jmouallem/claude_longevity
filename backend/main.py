from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from db.database import engine, Base, run_startup_migrations
from auth.routes import router as auth_router
from api.settings import router as settings_router
from api.chat import router as chat_router
from api.images import router as images_router
from api.logs import router as logs_router
from api.summaries import router as summaries_router
from api.specialists import router as specialists_router
from api.feedback import router as feedback_router
from api.intake import router as intake_router

# Create all tables
Base.metadata.create_all(bind=engine)
run_startup_migrations()

app = FastAPI(title="The Longevity Alchemist", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Serve frontend static files (in production)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "The Longevity Alchemist"}
