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



