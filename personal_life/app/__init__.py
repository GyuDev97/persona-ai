import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings, load_env_file
from .storage.database import initialize_database
from .services.environment_check_service import build_environment_check
from pathlib import Path


FRONTEND_SHARED_DIR = Path(__file__).resolve().parent / "frontend" / "shared"
logger = logging.getLogger("gyuos.startup")


def create_app() -> FastAPI:
    # Import the full route registry only when the application is created.
    # Event services can then be imported independently of optional dashboard
    # dependencies, while the running FastAPI application is unchanged.
    from .api.routes import router

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

    try:
        initialize_database()
    except Exception:
        # Database is a Core requirement, unlike camera/HUD/TTS integrations.
        # Do not include credentials or full DSNs in logs.
        logger.exception(
            "Database initialization failed (backend=%s). Check DB_BACKEND, host/port reachability, and database configuration.",
            get_settings().db_backend,
        )
        raise
    environment = build_environment_check()
    capabilities = environment["capabilities"]
    logger.info(
        "GYUVIS Environment Check | OS=%s arch=%s Python=%s DB=%s posture=%s entrance=%s HUD=%s TTS=%s",
        environment["os"],
        environment["architecture"],
        environment["python"],
        environment["database"]["status"],
        capabilities["posture_monitor"],
        capabilities["entrance_sensor"],
        capabilities["hud_overlay"],
        capabilities["tts"],
    )
    if FRONTEND_SHARED_DIR.exists():
        app.mount("/shared", StaticFiles(directory=FRONTEND_SHARED_DIR), name="shared")
    app.include_router(router)
    return app
