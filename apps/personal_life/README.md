# Personal Life Assistant

개인 생활용 비서 AI의 첫 번째 MVP입니다.  
지금 버전은 대화형 코어를 붙이기 전에, 생활 데이터를 쌓기 위한 최소 API와 저장소를 먼저 준비합니다.

## 포함된 기능

- `오늘 브리핑` 조회
- `빠른 기록` 저장
- `할 일` 등록
- `할 일 완료` 처리
- `일정` 등록 및 조회
- `루틴` 등록 및 체크인

## 폴더 구조

- `main.py`: FastAPI 진입점
- `app/api`: 라우터
- `app/domain`: Pydantic 스키마
- `app/services`: 비즈니스 로직
- `app/storage`: SQLite 초기화와 접근
- `data/personal_life.db`: 자동 생성되는 로컬 DB

## 실행 방법

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

기본 주소:

- `GET /health`
- `GET /briefing/today`
- `POST /captures`
- `GET /captures`
- `POST /tasks`
- `GET /tasks`
- `POST /tasks/{task_id}/done`
- `POST /schedules`
- `GET /schedules`
- `POST /routines`
- `GET /routines`
- `POST /routines/{routine_id}/checkins?day=YYYY-MM-DD&status=done`

## 예시 요청

빠른 기록:

```json
{
  "capture_type": "note",
  "content": "오늘 운동 30분 했다",
  "source": "manual"
}
```

할 일 등록:

```json
{
  "title": "보험 서류 정리",
  "details": "이번 주 안에 스캔까지 끝내기",
  "due_date": "2026-04-25",
  "priority": 1
}
```

일정 등록:

```json
{
  "title": "치과 방문",
  "details": "검진 후 스케일링 문의",
  "scheduled_for": "2026-04-23",
  "start_time": "14:00"
}
```

루틴 등록:

```json
{
  "name": "아침 스트레칭",
  "description": "기상 후 10분",
  "frequency": "daily"
}
```

## 다음 추천 단계

- 자연어 입력을 구조화하는 LLM 레이어 연결
- 주간 리뷰 API 추가
- 간단한 웹 대시보드 추가
