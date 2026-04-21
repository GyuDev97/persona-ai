# GW Assistant FastAPI

## 실행

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

접속:
- UI: http://localhost:8000
- Health: http://localhost:8000/health
- Swagger: http://localhost:8000/docs

## API

- `POST /api/eapproval/extract`
- `POST /api/eapproval/upload`

## 업로드 지원 범위

- 현재 데모는 텍스트 파일(`.txt`, `.md`, `.csv`, `.log`)과 엑셀(`.xlsx`), PDF(`.pdf`) 업로드를 지원합니다.
- 엑셀은 표준 라이브러리 기반으로 시트 텍스트를 읽습니다.
- PDF는 디지털 텍스트 PDF를 우선 지원합니다.
- 스캔본 PDF나 이미지형 PDF는 OCR이 추가되어야 안정적으로 추출됩니다.
