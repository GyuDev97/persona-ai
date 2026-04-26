# PC Wake Mode

`pc_wake_listener.py`는 PC 마이크를 계속 듣다가 박수 패턴을 감지하고, 이어서 호출어를 인식하면 규비스가 바로 응답하는 실험용 웨이크 모드입니다.

기본 흐름:

1. 박수 두 번
2. `일어나`, `규비스`, `보스` 같은 호출어
3. 규비스가 `어서오세요 보스.`라고 응답
4. 이어서 추가 명령을 한 번 더 듣고 서버로 보냄

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

서버까지 같이 쓰려면 FastAPI 서버도 켜두면 좋습니다.

```powershell
uvicorn main:app --reload --host 0.0.0.0
```

## 환경 변수

- `GYUVIS_SERVER_URL`
  - 기본값: `http://127.0.0.1:8000`
- `GYUVIS_SEND_FOLLOWUP`
  - `1`: 추가 명령을 서버로 전달
  - `0`: 추가 명령은 출력만 함
- `GYUVIS_AUTO_LISTEN_FOLLOWUP`
  - `1`: 인사 뒤에 추가 명령까지 자동으로 들음
  - `0`: 인사만 하고 끝
- `GYUVIS_CLAP_THRESHOLD`
  - 박수 감도 조절
  - 기본값: `0.24`

예시:

```powershell
$env:GYUVIS_SERVER_URL="http://192.168.0.19:8000"
$env:GYUVIS_CLAP_THRESHOLD="0.20"
python pc_wake_listener.py
```

## 튜닝 팁

- 주변 소음에도 자꾸 깨어나면:
  - `GYUVIS_CLAP_THRESHOLD`를 올리기
- 박수를 쳐도 잘 못 잡으면:
  - `GYUVIS_CLAP_THRESHOLD`를 내리기
- 인사만 하고 싶으면:
  - `GYUVIS_AUTO_LISTEN_FOLLOWUP=0`

## 참고

이 모드는 실험용 프로토타입입니다.

- 박수 감지는 환경에 따라 민감도가 달라질 수 있습니다.
- 음성 인식은 네트워크 상태에 따라 느려질 수 있습니다.
- 더 정교하게 만들려면 나중에 호출어 모델, 오프라인 STT, 웹캠 감지까지 붙일 수 있습니다.
