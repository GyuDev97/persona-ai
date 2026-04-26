# PC Wake Mode

`pc_wake_listener.py`는 PC 마이크를 계속 듣다가 박수 패턴을 감지하고, 이어서 호출어를 인식하면 규비스가 바로 응답하는 실험용 웨이크 모드입니다.

기본 흐름:

1. 박수 두 번
2. `일어나`, `규비스`, `보스` 같은 호출어
3. 규비스가 `어서오세요 보스.`라고 응답
4. 이어서 한 번 더 명령을 듣고 서버로 보냄

## 설치

```powershell
cd D:\github\persona-ai\apps\personal_life
pip install -r requirements.txt
```

## 실행

```powershell
cd D:\github\persona-ai\apps\personal_life
python pc_wake_listener.py
```

서버까지 같이 연결하려면 FastAPI 서버도 켜두면 좋습니다.

```powershell
uvicorn main:app --reload --host 0.0.0.0
```

## 환경 변수

- `GYUVIS_SERVER_URL`
  - 기본값: `http://127.0.0.1:8000`
- `GYUVIS_SEND_FOLLOWUP`
  - `1`: 추가 명령을 서버로 전달
  - `0`: 추가 명령은 출력만
- `GYUVIS_AUTO_LISTEN_FOLLOWUP`
  - `1`: 인사 뒤에 추가 명령까지 자동으로 듣기
  - `0`: 인사만 하고 끝
- `GYUVIS_CLAP_THRESHOLD`
  - 박수 감도 조절
  - 기본값: `0.11`
- `GYUVIS_WAKE_RECORD_SECONDS`
  - 호출어 녹음 길이
  - 기본값: `4.0`
- `GYUVIS_DEBUG_AUDIO`
  - `1`: 마이크 RMS와 박수 후보 로그 출력
  - `0`: 기본 로그만 출력

예시:

```powershell
$env:GYUVIS_SERVER_URL="http://192.168.0.19:8000"
$env:GYUVIS_CLAP_THRESHOLD="0.08"
$env:GYUVIS_DEBUG_AUDIO="1"
python pc_wake_listener.py
```

## 잘 안 들릴 때

- 박수를 쳐도 반응이 없으면:
  - `GYUVIS_CLAP_THRESHOLD`를 더 낮춰보세요. 예: `0.08`
- 너무 자주 깨어나면:
  - `GYUVIS_CLAP_THRESHOLD`를 올려보세요. 예: `0.15`
- `일어나`가 잘 안 잡히면:
  - 박수 뒤에 0.3~0.5초 정도 쉬고 또박또박 말해보세요.
  - `GYUVIS_WAKE_RECORD_SECONDS`를 `5.0`으로 늘려볼 수 있습니다.
- 어디서 막히는지 보고 싶으면:
  - `GYUVIS_DEBUG_AUDIO=1`로 실행해서 RMS 로그를 확인하세요.

## 참고

이 모드는 실험용 프로토타입입니다.

- 박수 감지는 환경 소음과 마이크 특성에 따라 민감도가 달라집니다.
- 음성 인식은 네트워크 상태에 따라 느려질 수 있습니다.
- 더 정교하게 만들려면 나중에 호출어 전용 모델이나 오프라인 STT를 붙이는 방향이 좋습니다.
