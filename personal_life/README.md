# GyuVIS (규비스)

> 나를 대신 운영하는 **Personal Concierge OS**  
> 일정 · 루틴 · 자산 · 메모리 · 브리핑 · AI 명령을 하나의 시스템으로 연결하는 개인 운영 플랫폼

---

## Overview

GyuOS는 단순한 생산성 앱이 아닙니다.  
사용자의 삶과 업무를 **운영(Operate)** 하기 위한 웹 기반 퍼스널 OS입니다.

핵심 목표:

- 아침마다 자동 브리핑 제공
- 일정 / 할 일 / 루틴 통합 관리
- 자산 / 소비 흐름 정리
- 자연어 명령으로 빠른 실행
- 기억 기반 개인화 Assistant 구축
- 데스크톱/모바일 확장 가능한 구조

---

## Core Philosophy

기존 앱들은 기능 단위로 나뉘어 있습니다.

- 일정 앱
- 메모 앱
- 가계부 앱
- 할 일 앱
- AI 챗봇

GyuOS는 이를 분리하지 않고,

> **"한 사람의 하루를 하나의 운영 시스템으로 관리한다"**

라는 관점으로 설계되었습니다.

## Windows 및 macOS 실행

Core 서버와 센서 런타임은 하나의 Python 코드베이스를 사용합니다. Windows 전용
`.bat` 파일은 호환성을 위해 유지하지만, 새 설치에서는 아래의 공통 launcher를
사용합니다. launcher는 현재 활성화된 가상환경의 `sys.executable`을 사용하므로
`python.exe`나 `venv\\Scripts` 경로를 코드에 고정하지 않습니다.

### Windows 11 (x86_64)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts\start.py
```

### macOS Apple Silicon

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python3 scripts/start.py
```

The server listens on `http://127.0.0.1:8000`; use `--host`, `--port`,
`--reload`, or `--background` when needed. These commands work on either OS:

```bash
python scripts/status.py
python scripts/stop.py
python scripts/stop.py --force-port  # explicitly stop the listener on 8000
```

`GET /system/environment` provides the startup self-check: OS, architecture,
Python version, database reachability, and optional feature capabilities. A
missing camera/TTS/HUD integration is reported as unavailable or limited and
does not prevent the Core API from starting.

### Posture monitor

Install its isolated dependencies after activating the same environment:

```bash
python -m pip install -r posture_alert/requirements.txt
python -m posture_alert.calibration
python -m posture_alert.main
```

`POSTURE_CAMERA_INDEX` selects the webcam (default `0`). On macOS, allow your
terminal or Python IDE under **System Settings → Privacy & Security → Camera**.
The Windows click-through, multi-monitor flash is retained; macOS presents a
single-screen non-click-through flash when Tk permits it, so the API and
posture detection remain independent of this limited overlay feature.

### Entrance sensor

```bash
python -m pip install -r home_arrival_sensor/requirements.txt
python -m home_arrival_sensor.enroll
python -m home_arrival_sensor.main
```

`CAMERA_INDEX` selects the camera. On macOS grant the same Camera permission.
Use `FACE_PROVIDER=cpu` on Apple Silicon; GPU provider selection is optional
and is not required for sensor startup. OpenCV uses AVFoundation on macOS and
DirectShow on Windows through the shared adapter.

### Platform limits and dependencies

OpenCV, MediaPipe, ONNX Runtime, and InsightFace are installed as normal Python
dependencies; their wheel availability should be checked against the selected
Python version before deployment. MediaPipe 0.10.18 ships a macOS universal2
wheel, and current OpenCV/ONNX Runtime releases publish ARM64 macOS wheels.
`pywinauto`, direct Windows window movement, click-through overlays, and Excel
COM automation remain Windows-only optional features. On macOS, browser/file
launch falls back to the system default handler, HUD launches in a browser, and
TTS uses Edge TTS first then the built-in `say` command when fallback is
enabled. No Rosetta requirement is introduced.

---

# Main Features

## 1. Daily Briefing

하루 시작과 마무리를 위한 AI 브리핑 기능

### Morning Briefing

- 오늘 일정 요약
- 우선 Task 안내
- 루틴 체크
- 자산/소비 핵심 정보
- 오늘 집중 포인트

### Evening Briefing

- 오늘 완료한 일
- 미완료 항목
- 소비 정리
- 내일 준비사항

---

## 2. Task Flow

단순 To-do가 아닌 실행 흐름 중심 업무 시스템

- 할 일 생성
- 우선순위 분류
- 진행중 / 완료 상태 관리
- Agent 작업 큐 연동
- 반복 업무 자동화 기반

---

## 3. Schedule Management

일정을 빠르게 등록하고 조회할 수 있는 개인 캘린더 레이어

- 일정 생성
- 오늘 일정 보기
- 시간 기준 정렬
- 브리핑 연동

---

## 4. Routine Engine

습관과 루틴을 시스템적으로 관리

- 아침 루틴
- 운동 루틴
- 업무 시작 루틴
- 체크인 기록

---

## 5. Asset / Finance System

삶과 돈을 함께 관리하는 재무 모듈

- 자산 등록
- 자산 변화 추적
- 재무 브리핑
- 소비 인사이트 확장 가능

---

## 6. Memory Engine

사용자 데이터를 기억하고 개인화하는 메모리 계층

- 프로필 메모리 저장
- 성향 기억
- 루틴 패턴 학습
- 향후 AI 추천 시스템 기반

---

## 7. Natural Language Commands

자연어 기반 명령 처리

예시:

- "오늘 일정 보여줘"
- "내일 오전 회의 추가해줘"
- "오늘 할 일 정리해줘"
- "브리핑 시작"

---

## 8. Mobile Assistant Layer

모바일 환경 확장을 고려한 Assistant API 구조 포함

- 모바일 명령 전달
- 외부 디바이스 연동 가능
- 향후 모바일 앱 확장 대응

---

# Project Structure

```bash
GyuOS/
├── api/                  # FastAPI Router
│   └── routes.py
│
├── domain/               # Pydantic Schemas / DTO
│   └── schemas.py
│
├── frontend/             # Web UI
│   ├── index.html
│   ├── briefing.html
│   ├── schedule.html
│   ├── money.html
│   ├── routine.html
│   └── mobile/
│
├── services/             # Core Business Logic
│   ├── briefing_service.py
│   ├── task_service.py
│   ├── schedule_service.py
│   ├── finance_service.py
│   ├── memory_service.py
│   ├── natural_language_service.py
│   ├── desktop_action_service.py
│   └── ...
│
├── storage/
│   └── database.py
│
└── config.py


