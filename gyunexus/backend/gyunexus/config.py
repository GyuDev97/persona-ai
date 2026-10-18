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
    proactive_enabled: bool = True  # 능동 제안 전체 on/off(대시보드에서 바꾸면 DB 값이 우선)
    proactive_quiet_hours: str = "23:00-07:00"  # 이 시간대에는 제안을 보류한다. 빈 문자열이면 사용 안 함
    proactive_deliver_threshold: float = 0.62  # 점수 이상이면 전달 후보, 아래 drop 임계값 미만이면 폐기, 사이는 LLM이 판단
    proactive_drop_threshold: float = 0.40
    proactive_dashboard_event_gap_minutes: int = 10  # 같은 접속 이벤트가 짧은 시간에 반복 처리되지 않도록
    proactive_sky_horizon_nights: int = 3  # 오늘 밤부터 몇 밤까지 출사 후보를 살필지
    proactive_candidate_ttl_hours: int = 6  # 날씨 조회에 기반한 후보의 유효 시간

    # AI 직원(Workers)
    worker_min_interval_minutes: int = 5  # 정기 업무의 최소 주기
    worker_max_tool_calls: int = 4  # 실행 1회당 도구 호출 상한
    worker_materials_max_chars: int = 20000  # 업무에 직접 붙이는 자료의 총 글자 수 상한
    worker_output_max_chars: int = 30000
    worker_input_max_chars: int = 30000  # 선행 단계 Artifact 를 입력으로 받을 때의 총 글자 수 상한

    # 워크플로(여러 AI 직원의 협업 실행)
    workflow_max_steps: int = 12
    workflow_max_parallel: int = 3  # 한 워크플로에서 동시에 실행하는 단계 수
    workflow_default_budget_usd: float = 0.5
    workflow_max_budget_usd: float = 5.0
    worker_notify_gap_minutes: int = 60  # 같은 업무의 '완료' 알림 최소 간격(승인 필요·실패는 별도 규칙)

    # 통합 자율 실행(autonomy.py). 기본값은 모두 보수적이다: 상시 자율 운영은 꺼져 있고, 자동 승인은 자율(autonomous) 모드에서만 가능하다.
    autonomy_enabled: bool = False  # 상시 자율 운영(트리거) 전체 on/off 의 초기값(화면에서 바꾸면 DB 값이 우선)
    autonomy_max_mode: str = "supervised"  # 자동 실행을 허용하는 최대 모드(supervised | autonomous). 요청·트리거의 모드는 이 값을 넘지 못한다
    autonomy_auto_approve: bool = True  # autonomous 모드에서 정책을 통과한 읽기 전용 결과물의 자동 승인을 허용할지
    autonomy_max_concurrent: int = 2  # 트리거가 시작한 워크플로의 동시 실행 상한
    autonomy_daily_cost_cap_usd: float = 1.0  # 트리거가 시작한 모든 워크플로의 하루 비용 상한
    autonomy_min_interval_minutes: int = 5  # 반복 트리거의 최소 간격
    autonomy_max_chain_depth: int = 3  # 선행 업무 완료로 이어지는 연쇄의 최대 깊이
    autonomy_retry_delay_minutes: int = 2  # 실패한 워크플로를 자동 재시도하기 전 대기
    autonomy_request_max_retries: int = 1  # 요청형(대화·화면) 자율 실행의 자동 재시도 상한
    autonomy_missed_grace_minutes: int = 60  # 한 번만 실행하는 트리거가 이 시간 넘게 늦으면 실행하지 않고 건너뜀으로 기록

    # 뉴스 수집 도구(rss.fetch / news.search / web.fetch)
    web_fetch_max_bytes: int = 1_500_000  # 원문 HTML 응답 크기 상한
    web_fetch_timeout_seconds: float = 10.0
    web_fetch_max_redirects: int = 4
    news_cache_seconds: float = 300.0  # 같은 피드를 이 시간 안에 다시 받지 않는다
    feed_timeout_seconds: float = 15.0
    feed_max_bytes: int = 3_000_000  # RSS/Atom 응답 크기 상한(가장 큰 공식 피드가 약 1.5MB)

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
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspace"

    @property
    def notes_dir(self) -> Path:
        return self.data_dir / "notes"
