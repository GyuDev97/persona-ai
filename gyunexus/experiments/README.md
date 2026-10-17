# 멀티 에이전트 협업 품질 비교 실험

GyuNexus 소스는 수정하지 않고, 이 폴더에서 세 방식(A 단일 LLM, B 현재 멀티 에이전트, C 실험용 Hybrid)을 같은 주제 16개로 비교했다.
평가 기준과 점수 산정은 실행 전에 `PROTOCOL.md`로 고정했다(SHA-256 `af24c4e3...9b95`, `results_protocol_sha256.txt`).

| 파일 | 내용 |
|---|---|
| `PROTOCOL.md` | 사전 고정 프로토콜(방식, 조건, 루브릭, 집계, 한계) |
| `topics.py` | 주제 16개, 공통 배경 자료, 증거 번들 사양 |
| `hybrid.py` | C(Hybrid) 구현: 오케스트레이터 상속 + 실험 중에만 정규식 대체 |
| `run_experiment.py` | 생성(`gen`)·평가(`judge`) 실행기, 예산 상한($0.48 하드 스톱) |
| `judge_extra.py`, `ablation.py` | 프로토콜 이후 추가한 사후 점검(다른 평가자, 증거 합집합, Critic 제거) |
| `analyze.py` | 집계 → `results/analysis.md`, `summary.json` |
| `results/raw/` | 주제×방식 원본 결과(토론 전문, 증거, 아이디어, 사용량) |
| `results/judge/` | 평가자 점수와 근거 메모, 탐지기 비교 |
| `results/review_blind.md`, `review_key.json` | 사람이 블라인드로 검토하기 위한 후보 모음과 매핑 |

재실행(키는 `.env`에서 읽는다): `python run_experiment.py gen` → `judge` → `python analyze.py`.
