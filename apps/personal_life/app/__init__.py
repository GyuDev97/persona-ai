from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import load_env_file
from .storage.database import initialize_database
from pathlib import Path


FRONTEND_SHARED_DIR = Path(__file__).resolve().parent / "frontend" / "shared"


def create_app() -> FastAPI:
    load_env_file()

    app = FastAPI(
        title="Personal Life Assistant",
        version="0.1.0",
        description="A lightweight personal assistant API for daily briefings and quick capture.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    initialize_database()
    if FRONTEND_SHARED_DIR.exists():
        app.mount("/shared", StaticFiles(directory=FRONTEND_SHARED_DIR), name="shared")
    app.include_router(router)
    return app
