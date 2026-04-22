# Mail Assistant MVP

웹 쪽지함으로 메일 어시스턴트 흐름을 먼저 테스트하는 작은 FastAPI 앱입니다.
저장은 로컬 MariaDB를 기본으로 사용합니다.

## 포함 기능

- 웹 폼으로 새 쪽지 입력
- 답장 필요 여부 분류: `reply`, `ignore`, `review`
- 분류 이유 생성
- 답장 초안 생성
- 저장된 쪽지 목록 조회

## 실행

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

접속:

- UI: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`
- Swagger: `http://127.0.0.1:8000/docs`

## DB 기본값

- DBMS: MariaDB
- host: `127.0.0.1`
- port: `3306`
- user: `root`
- password: 빈 문자열
- database: `mail_assi`

앱이 처음 요청을 받을 때 `mail_assi` 데이터베이스와 `messages` 테이블을 자동으로 생성합니다.
필요하면 아래 환경변수로 바꿀 수 있습니다.

```bash
MAIL_ASSI_DB_HOST=127.0.0.1
MAIL_ASSI_DB_PORT=3306
MAIL_ASSI_DB_USER=root
MAIL_ASSI_DB_PASSWORD=
MAIL_ASSI_DB_NAME=mail_assi
```

## 구조

- `main.py`: FastAPI 앱 진입점
- `backend/routers/inbox.py`: 메시지 저장/조회 API
- `backend/services/db.py`: MariaDB 연결과 스키마 초기화
- `backend/services/mail_logic.py`: 분류와 초안 생성 로직
- `frontend/index.html`: 웹 쪽지함 UI

## 다음 확장 아이디어

- 실제 LLM API 연동으로 분류/초안 품질 개선
- 승인 후 발송 플로우 추가
- Gmail 입력 소스 연결
