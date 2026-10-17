# Company AI - Dev Worker V1 인수인계

## 1. 목적

`company-ai`는 요구사항을 받아 격리된 Git worktree에서 Codex CLI로 구현하고, Build/Test/재시도/보고서를 관리하는 로컬 Dev Worker입니다.

- 프로젝트 경로: `D:\github\persona-ai\apps\personal_life\company-ai`
- Python 실행 환경: `D:\python\venv\Scripts\python.exe`
- 웹 화면: FastAPI 기반 단일 페이지 대시보드

## 2. 실행 방법

프로젝트 루트에서 아래 명령을 실행합니다.

```powershell
& 'D:\python\venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8019
```

브라우저에서 `http://127.0.0.1:8019`를 엽니다.

테스트는 다음과 같이 실행합니다.

```powershell
& 'D:\python\venv\Scripts\python.exe' -m compileall -q app tests
& 'D:\python\venv\Scripts\python.exe' -m unittest discover -s tests -v
```

## 3. 주요 구성

| 경로 | 역할 |
| --- | --- |
| `app/main.py` | FastAPI API 및 SSE 엔드포인트 |
| `app/dev_worker.py` | 작업 생성, Worktree, Codex, Build/Test, 재시도, 이벤트 처리 |
| `app/database.py` | SQLite 테이블 및 DB 접근 |
| `app/models.py` | 요청/응답 모델과 상태 정의 |
| `app/project_manager.py` | 프로젝트 Profile 로드 및 Git worktree 준비 |
| `app/codex_runner.py` | Codex CLI 실행 |
| `app/build_runner.py` | Build/Test 명령 실행 |
| `app/report_generator.py` | 작업 보고서 생성 |
| `profiles/sample_project.yaml` | 샘플 Python 프로젝트 설정 |
| `web/index.html` | 카드형 대시보드 구조 |
| `web/style.css` | 다크 네이비 카드 UI 및 반응형 스타일 |
| `web/app.js` | API 호출, 대시보드 렌더링, SSE 수신 |
| `tests/test_core.py` | Worker 핵심 흐름 단위 테스트 |

## 4. 작업 흐름

1. 사용자가 프로젝트와 요구사항을 입력해 작업을 생성합니다.
2. Worker가 프로젝트 Profile을 읽고, 격리된 Git worktree를 `workspace/<TASK-ID>`에 준비합니다.
3. Codex CLI가 해당 Worktree에서 코드를 수정합니다.
4. Build와 Test를 수행합니다.
5. 실패 시 Profile의 최대 시도 횟수까지 자동 수정 후 재실행합니다.
6. 최종 상태와 보고서를 저장하고, 작업 결과를 화면에 표시합니다.

기본 상태값은 내부적으로 영문을 유지합니다.

`PENDING`, `PREPARING`, `RUNNING_CODEX`, `BUILDING`, `TESTING`, `RETRYING`, `SUCCESS`, `FAILED`, `FAILED_NEEDS_HUMAN`, `CANCELLED`

화면 표시는 `web/app.js`의 `STATUS_LABELS`에서 한국어로 공통 변환합니다.

## 5. API

| API | 용도 |
| --- | --- |
| `GET /api/health` | 서버 상태 확인 |
| `GET /api/projects` | 프로젝트 Profile 목록 |
| `POST /api/tasks` | 새 작업 생성 |
| `GET /api/tasks` | 최근 작업 목록 |
| `GET /api/tasks/{task_id}` | 작업 상세, 시도 이력, 로그, 보고서 |
| `GET /api/tasks/{task_id}/events?after={event_id}` | 사용자용 실시간 SSE 이벤트 |
| `POST /api/tasks/{task_id}/cancel` | 실행 중 작업 취소 |

## 6. 최근 작업 정렬 원칙

작업 목록은 프런트엔드 배열 순서에 의존하지 않습니다. 백엔드에서 다음 기준으로 정렬합니다.

```sql
ORDER BY created_at DESC, id DESC
```

따라서 새로 만든 작업은 목록 맨 위에 표시되고, 상태가 변경되어도 위치는 바뀌지 않습니다.

## 7. 대시보드 UI 구조

- 좌측: Dev Worker 메뉴와 시스템 상태
- 상단: 전체 작업 / 진행 중 / 완료 / 확인 필요 / 실패 KPI
- 중단 좌측: 새 작업 입력 폼
- 중단 우측: 현재 작업 6단계 진행상황
- 하단 좌측: 생성일 최신순 최근 작업
- 하단 중앙: 선택 작업의 요약, 결과, 보고서, 시도 이력
- 하단 우측: 사용자용 실시간 작업 로그

원본 stdout/stderr 성격의 로그는 기본 로그와 분리되어 작업 요약의 **전체 로그 보기**로 확인합니다.

## 8. 확인 완료 항목

- Python 핵심 테스트 5건 통과
- 최근 작업이 생성 시각 최신순으로 표시되는 것 확인
- 작업 선택 후에도 목록 위치가 바뀌지 않는 것 확인
- 새로고침 후 목록 정렬 유지 확인
- 상태 Badge 한국어 표시 확인
- 완료 작업의 6단계 진행 상태, 요약 카드, 사용자 이벤트 로그 표시 확인
- 브라우저 콘솔 오류 없음 확인

## 9. 운영 시 유의사항

- Codex CLI와 Git이 실행 가능한 로컬 환경이어야 실제 코드 작업이 진행됩니다.
- `sample_repo`는 Worker 동작 확인용 별도 Git 저장소입니다.
- Worker 생성 Worktree와 보고서는 각각 `workspace/`, `reports/`에 생성됩니다.
- 이번 UI 개편은 `web/` 파일만 변경했으며, Worker 핵심 로직과 기존 API 구조는 변경하지 않았습니다.
