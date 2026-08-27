# Company AI · Dev Worker V1

회사 프로젝트의 요구사항을 Codex CLI 한 인스턴스로 실행하고, 격리된 Git worktree에서 Build/Test 및 최대 3회의 자동 수정 재시도를 수행하는 로컬 POC입니다. `personal-ai`와 GYUVIS의 코드나 데이터에는 연결하지 않습니다.

## V1 안전 경계

- Profile의 원본 저장소는 수정하지 않습니다. 작업마다 `workspace/TASK-*` Git worktree를 `--detach`로 만듭니다.
- Codex는 해당 worktree만 작업 경로로 받고 workspace-write sandbox로 일회성(`--ephemeral`) 실행됩니다.
- push, merge, commit, 배포, 운영 환경 접근, DB schema 변경은 Codex prompt에서 금지합니다.
- Profile의 `protected_paths` 변경을 발견하면 성공으로 끝내지 않고 `FAILED_NEEDS_HUMAN`으로 중단합니다.
- 재시도 횟수는 Profile 값과 관계없이 최대 3회입니다. 자동 정리/자동 merge/자동 commit은 하지 않으므로 결과 worktree와 diff는 사용자가 검토할 수 있습니다.

## Run

```powershell
cd D:\github\persona-ai\apps\personal_life\company-ai
& "D:\python\venv\Scripts\python.exe" -m pip install -r requirements.txt
& "D:\python\venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

브라우저에서 `http://127.0.0.1:8010`을 열고 **Sample Python Project**를 선택합니다. Codex CLI가 이 사용자 계정에 로그인되어 있어야 실제 작업이 실행됩니다.

## Profile

`profiles/*.yaml` 하나가 하나의 프로젝트입니다. 아래 필드는 V1에서 필요합니다.

```yaml
id: payroll-service
name: Payroll Service
repo_path: D:/workspace/payroll-service
build_command: mvn clean package
test_command: mvn test
retry_limit: 3
rules:
  - Preserve the existing structure.
protected_paths:
  - config/prod
  - deploy
  - .env
```

`repo_path`는 Git checkout이어야 하며, YAML 파일 기준의 상대 경로도 사용할 수 있습니다. Build/Test command는 신뢰할 수 있는 로컬 Profile 작성자만 추가해야 합니다.

## Result locations

- SQLite task history: `data/company_ai.db`
- live Codex output / final message: `logs/`
- Markdown and JSON reports: `reports/TASK-*.{md,json}`
- reviewable isolated changes: `workspace/TASK-*`

## Verification

```powershell
& "D:\python\venv\Scripts\python.exe" -m unittest discover -s tests -v
```

The included tests use a fake Codex runner and forced Build/Test error to verify the three-attempt ceiling, state transition, report generation, profile retry clamp, and safety context. They do not invoke a paid/live Codex session.
