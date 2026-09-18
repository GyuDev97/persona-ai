import os
from dataclasses import dataclass
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = APP_ROOT / ".env"


@dataclass
class Settings:
    openai_api_key: str | None
    openai_model: str
    default_observation_location: str
    night_sky_http_timeout_seconds: float
    night_sky_use_llm_summary: bool
    db_backend: str
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def get_settings() -> Settings:
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        default_observation_location=os.getenv("DEFAULT_OBSERVATION_LOCATION", "Seoul, South Korea"),
        night_sky_http_timeout_seconds=float(os.getenv("NIGHT_SKY_HTTP_TIMEOUT_SECONDS", "8")),
        night_sky_use_llm_summary=os.getenv("NIGHT_SKY_USE_LLM_SUMMARY", "0") == "1",
        db_backend=os.getenv("DB_BACKEND", "sqlite").lower(),
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_user=os.getenv("DB_USER", "root"),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_name=os.getenv("DB_NAME", "personal_life"),
    )
