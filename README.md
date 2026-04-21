# 개인 AI 실험실

혼자서 만들고 싶었던 AI 아이디어들을 직접 구현해보는 저장소입니다.

외부 API에만 의존하지 않고  
로컬 GPU 기반 LLM 파인튜닝부터  
개인 비서 AI, 업무 자동화, 그룹웨어 AI까지 실험합니다.

작지만 실제로 쓸 수 있는 AI를 만드는 것이 목표입니다.

## 🚧 진행 중인 실험

- 개인 비서형 AI 에이전트
- 사내 그룹웨어 AI 어시스턴트
- 로컬 RAG 문서 검색 시스템
- 음성 기반 AI 인터페이스
- 멀티모달 AI 실험 (텍스트 + 이미지)
- AI사진 검색(Windows App)

- 
## 🎯 목표

- 외부 서비스 의존도를 낮춘 개인 AI 구축
- 실제 업무에 도움이 되는 생산성 AI 개발
- 로컬 환경에서도 충분히 강력한 AI 만들기

## 🚀 주요 기술
- Polyglot 5.8B 기반 LoRA 파인튜닝
- 4bit 양자화로 VRAM 최적화 (RTX 3060 12GB 기준)
- 개인 데이터셋(질문·답변)으로 AI 학습
- FastAPI 기반 API 서버 제공
- 모델 추론 테스트 스크립트 포함

📂 프로젝트 구조
persona-ai/
│── apps/
│   ├── gw_assistant/
│   ├── personal_agent/
│   ├── rag_search/
│   └── chatbot/
│
│── core/
│   ├── llm/
│   ├── prompts/
│   ├── db/
│   ├── vector/
│   └── utils/
│
│── experiments/
│── tests/
│── pyproject.toml
│── README.md

- 
## 🛠 환경 설정

1️⃣ WSL 설치
- Windows 기능 켜기/끄기 →
- ✅ Hyper-V
- ✅ Linux용 Windows 하위 시스템(WSL2) 활성화 → 재부팅

- 명령 프롬프트(관리자 권한) 실행 후:
- wsl --install -d Ubuntu-22.04
- 설치 후 사용자 계정명과 암호 입력
- 재실행 시 시작 메뉴 → WSL 검색하여 실행

2️⃣ Python 환경 구성
- sudo apt update && sudo apt install python3.10 python3.10-venv python3-pip -y
- python3.10 -m venv venv
- source venv/bin/activate
- cd /mnt/d/AI_python

3️⃣ 필수 패키지 설치
- pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0
- pip install transformers peft datasets accelerate bitsandbytes
- pip install fastapi uvicorn

---
## 💻 실행 방법

- 데이터 셋(아래와 같은형태로 여러개를 만든다)
> {"instruction": "너는 누구야?", "input": "", "output": "저는 주인님이 직접 개발하신 AI 비서입니다."}

- 학습
> python train.py

- 테스트
> python test.py

- API 서버 실행(웹 채팅형태)
> python app.py(localhost:8000/chat으로 접근가능)

---
## ⚠️ 주의사항
- RTX 3060 (VRAM 12GB) 기준으로 작성 → 낮은 사양 GPU에서는 OOM(Out of Memory) 발생 가능
- 인텔 내장 GPU 노트북은 지원 불가
- 학습 데이터가 많을수록 학습 시간이 오래 걸립니다.
- 데스크톱 사용 시 에어컨 + 본체 뚜껑 열기, 노트북 사용 시 쿨러 필수
