from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="GYUNEXUS_", extra="ignore", populate_by_name=True
    )

    # LLM 설정
    openai_api_key: str = Field("", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4o-mini", validation_alias="OPENAI_MODEL")
    openai_base_url: str = Field("", validation_alias="OPENAI_BASE_URL")
    price_in_per_m: float = 0.15  # 프롬프트 100만 토큰당 USD (비용 추정용)
    price_out_per_m: float = 0.60  # 응답 100만 토큰당 USD

    # 저장소
    database_url: str = ""  # 비우면 data/ 아래 SQLite 파일 사용
    data_dir: Path = ROOT / "data"

    # 사용자 상황
    timezone: str = "Asia/Seoul"
    latitude: float | None = None
    longitude: float | None = None
    presence_timeout_seconds: int = 300

    # 자율 워크스페이스
    autonomous_enabled: bool = True
    debate_interval_minutes: int = 180
    daily_budget_usd: float = 0.50  # 자율 작업 LLM 비용의 하루 상한
    debate_min_rounds: int = 2
    debate_max_rounds: int = 3
    debate_max_tokens: int = 24000  # 토론 1건당 상한(종합 단계 예비분 포함)
    debate_critic_retries: int = 2  # 토론 1건당 거부된 Critic 반박을 다시 쓰게 하는 최대 횟수(발언당 1회)
    scheduler_tick_seconds: int = 30

    # 능동 제안 엔진
    importance_threshold: int = 7  # 이 중요도 이상이면 GYUVIS가 사용자에게 전달
    proactive_cooldown_minutes: int = 360
    proactive_daily_max: int = 3
    proactive_check_minutes: int = 30

    # 대화 / 기억
    chat_history_limit: int = 20
    memory_top_k: int = 8

    # 외부 도구 호출: 타임아웃(초), 재시도 간 대기(초, 길이+1 = 최대 시도 횟수), 예보 조회 가능 일수
    tool_timeout_seconds: float = 8.0
    tool_retry_backoff: list[float] = [0.5, 1.5]
    forecast_max_days: int = 7

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'gyunexus.db').as_posix()}"

    @property
    def notes_dir(self) -> Path:
        return self.data_dir / "notes"
