"""실험 주제와 공통 배경 자료. 실험 시작 전에 고정한다(PROTOCOL.md 참고)."""

BRIEF_USER = (
    "[사용자 배경] 개인 개발자. Python/FastAPI/React로 개인 AI 비서 GyuNexus를 개발 중이며, 은하수 촬영이 취미라 주말 출사 전에 "
    "날씨와 천문 정보를 자주 확인한다."
)

BRIEF_GYUNEXUS = (
    "[GyuNexus 현재 구현 사실]\n"
    "- 백엔드 FastAPI + SQLAlchemy(SQLite, MariaDB 전환 가능), 프런트 React+TypeScript, 실시간 이벤트는 SSE.\n"
    "- LLM은 OpenAI(gpt-4o-mini)이며 Provider 교체 가능. 호출마다 토큰·비용을 기록하고 자율 작업에는 일일 예산 상한이 있다.\n"
    "- 기억: 대화에서 LLM이 장기 정보를 추출해 저장한다. 검색은 임베딩 없이 문자 bigram 유사도 + 중요도 + 최신성 점수로 순위를 매긴다.\n"
    "- 대화: 최근 20개 메시지만 사용(오래된 대화 요약 없음). 세션별로 주제·날짜·장소 상태를 저장해 후속 질문을 처리하고, 날씨·달 위상 읽기 도구를 연동한다.\n"
    "- 도구: read 도구는 자동 실행, write/external 도구는 사용자 승인 큐를 거친다.\n"
    "- 에이전트: Research/Idea/Developer/Critic. 규칙 기반 참가자 선택, 증거 검증 장부, 최대 3라운드, 토큰·예산 상한, 결과를 "
    "accepted/needs_research/discarded로 분류한다.\n"
    "- 아직 없음: 음성/TTS, 캘린더·일정 연동, 임베딩 검색, 오래된 대화 요약, 뉴스 도구, PC 제어."
)

# area: 평가 영역 / gyunexus: GyuNexus 구현 사실을 배경에 포함 / bundle: 증거 번들(도구 결과) 사양 — None이면 증거 없음
# bundle 항목: (도구, 날짜 오프셋 또는 'SAT'/'SUN', 시간대)
TOPICS = [
    # GyuNexus 아키텍처 개선
    {"id": "arch1", "area": "GyuNexus 아키텍처", "gyunexus": True, "bundle": None,
     "title": "GyuNexus의 기억 검색을 임베딩 없이 정확도를 높이는 방법은 무엇일까?"},
    {"id": "arch2", "area": "GyuNexus 아키텍처", "gyunexus": True, "bundle": None,
     "title": "GyuNexus 에이전트 토론 결과의 품질을 자동으로 평가하는 지표를 어떻게 설계할까?"},
    {"id": "arch3", "area": "GyuNexus 아키텍처", "gyunexus": True, "bundle": None,
     "title": "대화 상태 라우팅에 일정·교통 같은 새 주제를 안전하게 추가하는 구조는 어떻게 만들까?"},
    # AI 에이전트 협업
    {"id": "collab1", "area": "AI 에이전트 협업", "gyunexus": True, "bundle": None,
     "title": "여러 LLM 에이전트가 서로의 오류를 줄이는 토론 프로토콜은 어떻게 설계할까?"},
    {"id": "collab2", "area": "AI 에이전트 협업", "gyunexus": True, "bundle": None,
     "title": "에이전트 토론의 비용을 줄이면서 결과 품질을 유지하는 시스템 설계는?"},
    {"id": "collab3", "area": "AI 에이전트 협업", "gyunexus": True, "bundle": None,
     "title": "에이전트가 존재하지 않는 도구 결과를 인용하는 환각을 막는 시스템은 어떻게 만들까?"},
    # 개발 생산성·자동화
    {"id": "dev1", "area": "개발 생산성", "gyunexus": False, "bundle": None,
     "title": "개인 개발자가 반복적인 코드 리뷰를 자동화하는 워크플로는 어떻게 구성할까?"},
    {"id": "dev2", "area": "개발 생산성", "gyunexus": False, "bundle": None,
     "title": "테스트 코드 작성 시간을 줄이는 AI 활용 방식은 무엇일까?"},
    # 개인 AI 비서 활용
    {"id": "asst1", "area": "개인 AI 비서", "gyunexus": True, "bundle": None,
     "title": "개인 AI 비서가 사용자의 집중 시간을 존중하면서 먼저 말을 거는 규칙을 시스템으로 어떻게 설계할까?"},
    {"id": "asst2", "area": "개인 AI 비서", "gyunexus": True, "bundle": None,
     "title": "개인 AI 비서가 PC 제어 같은 위험한 작업을 안전하게 위임받는 승인 시스템은 어떻게 설계할까?"},
    # 은하수 촬영·기상 (사실 확인 필요: 증거 번들)
    {"id": "sky1", "area": "은하수·기상", "gyunexus": False,
     "bundle": [("weather.forecast", 0, "밤"), ("weather.forecast", 1, "밤"), ("astro.moon_phase", 0, "밤"), ("astro.moon_phase", 1, "밤")],
     "title": "오늘 밤과 내일 밤 중 은하수 출사에 더 나은 날은 언제일까?"},
    {"id": "sky2", "area": "은하수·기상", "gyunexus": False,
     "bundle": [("weather.forecast", "SAT", "밤"), ("weather.forecast", "SUN", "밤"), ("astro.moon_phase", "SAT", "밤"), ("astro.moon_phase", "SUN", "밤")],
     "title": "이번 주말 은하수 출사 계획: 어느 날 어떤 시간대에 가고 무엇을 준비해야 할까?"},
    {"id": "sky3", "area": "은하수·기상", "gyunexus": False,
     "bundle": [("weather.forecast", 0, "밤"), ("weather.forecast", 0, "저녁"), ("astro.moon_phase", 0, "밤")],
     "title": "오늘 밤 기상과 달 조건에서 은하수 촬영이 어렵다면 대신 무엇을 하면 좋을까?"},
    # 새로운 개인 프로젝트 아이디어
    {"id": "proj1", "area": "개인 프로젝트", "gyunexus": False, "bundle": None,
     "title": "하루 안에 만들 수 있는 개인 사진 정리 자동화 도구 아이디어는 무엇일까?"},
    {"id": "proj2", "area": "개인 프로젝트", "gyunexus": False, "bundle": None,
     "title": "개인 천체사진 기록을 활용한 작은 웹앱 프로젝트 아이디어는 무엇일까?"},
    {"id": "proj3", "area": "개인 프로젝트", "gyunexus": False, "bundle": None,
     "title": "로컬 LLM과 FastAPI로 만드는 개인 지식 검색 도구는 어떻게 구성할까?"},
]

SEED_MEMORIES = [
    ("interest", "사용자는 은하수 촬영을 즐긴다", 9),
    ("routine", "사용자는 주말 출사를 위해 날씨와 천문 정보를 자주 확인한다", 7),
    ("goal", "사용자는 Python/FastAPI/React로 개인 AI 비서 GyuNexus를 개발 중이다", 8),
]


def brief_for(topic: dict) -> str:
    return BRIEF_USER + ("\n" + BRIEF_GYUNEXUS if topic["gyunexus"] else "")
