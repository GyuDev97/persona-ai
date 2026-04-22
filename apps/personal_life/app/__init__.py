from fastapi import FastAPI

from .api.routes import router
from .config import load_env_file
from .storage.database import initialize_database


def create_app() -> FastAPI:
    load_env_file()

    app = FastAPI(
        title="Personal Life Assistant",
        version="0.1.0",
        description="A lightweight personal assistant API for daily briefings and quick capture.",
    )

    initialize_database()
    app.include_router(router)
    return app
