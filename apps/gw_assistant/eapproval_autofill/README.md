# GW Assistant 전자결재 자동입력 데모

네 가지 전자결재 양식에 첨부 문서의 내용을 자동으로 매핑하는 사전 검증용 프로토타입입니다. 실제 결재 상신, SSO, 결재선 연동은 포함하지 않습니다.

## 지원 양식

- 구매 신청서: 요청부서, 납품요청일, 품목/규격/수량/단가/금액, 비고
- 지출결의서: 요청부서, 결제예정일, 지출내역, 특이사항, 계좌정보
- 명함 신청서: 명함 정보 일체. 찾지 못한 값은 빈 값으로 유지합니다.
- 도서구입 신청서: 신청부서, 수령희망일, 구입사유, 도서 목록

양식 정의는 `backend/forms/*.json`에 있으며, 공통 영역(문서번호·기안자·결재선 등)은 분석 결과에 연결하지 않습니다.

처리는 세 단계로 분리합니다.

1. `backend/routers/eapproval.py`: PDF/XLSX/TXT 등 파일에서 텍스트를 추출합니다.
2. `backend/services/source_extraction.py`: 문서의 다양한 열 제목을 `name`, `spec`, `quantity`, `unitPrice`, `amount` 같은 공통 의미로 정규화합니다.
3. `backend/services/form_mapper.py`: 정규화된 결과를 현재 선택한 Form Schema의 필드·테이블에 매핑합니다.

`OPENAI_API_KEY`를 설정하면 `backend/services/ai_form_mapper.py`가 선택된 Form Schema와 추출 텍스트를 GPT Structured Outputs(JSON Schema)로 전달합니다. 응답은 `backend/services/result_validation.py`에서 타입·날짜·계산 관계를 검증한 뒤에만 화면으로 전달됩니다. 키가 없거나 GPT 요청이 실패하면 기존의 정규화 매퍼가 동작하고, 그 사실을 경고로 표시합니다.

따라서 `품명/규격/수량/단가/금액`, `제품명/모델명/QTY/공급단가/공급가액`, `ITEM/DESCRIPTION/EA/PRICE/TOTAL` 표는 모두 구매 품목의 같은 공통 구조로 처리됩니다.

## PDF 처리

PDF는 `backend/services/pdf_extraction.py`에서 PyMuPDF로 페이지별 텍스트를 읽습니다. 추출한 비공백 문자가 40자 미만이면 스캔/이미지 PDF로 분류하고 페이지를 PNG로 렌더링해 GPT Vision Structured Output 경로에 전달합니다. API 키 또는 Vision 호출이 없으면 스캔 PDF에 대해 명확한 오류를 반환하며 OCR 결과를 만들어내지 않습니다.

## 첨부파일 형식

`backend/services/document_extractor.py`는 파일 시그니처와 확장자를 함께 확인해 공통 `DocumentData`로 변환합니다. 지원 형식은 PDF, JPG/JPEG/PNG/WEBP, XLS/XLSX, CSV/TXT, DOCX, HWPX입니다. 이미지와 스캔 PDF는 Vision 분석을 사용하며, 표·문단·시트 구조는 텍스트와 테이블 데이터로 보존해 GPT에 전달합니다.

기존 DOC 및 HWP(OLE 형식)는 이 환경에 안정적인 변환기가 없으므로 지원하지 않으며, API가 정상적인 `415` 오류와 변환 안내를 반환합니다. 빈 파일, 손상된 파일, 25MB 초과 파일도 명확한 오류로 처리합니다.

## 실행

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8810
```

GPT 자동 매핑을 사용하려면 `.env.example`을 참고하여 시스템 환경변수 `OPENAI_API_KEY`를 설정하고, `pip install -r requirements.txt`를 다시 실행하세요. `.env`는 Git에서 제외됩니다.

프로젝트 루트에 `.env` 파일을 만들고 `OPENAI_API_KEY=...`를 넣어도 됩니다. 서버를 재시작한 뒤 `GET /api/eapproval/ai-status`에서 `configured: true`인지 확인하세요. 이 API는 키 값 자체를 반환하지 않습니다.

접속:
- UI: http://localhost:8810
- Health: http://localhost:8810/health
- Swagger: http://localhost:8810/docs

## API

- `GET /api/eapproval/forms` — 양식 목록
- `GET /api/eapproval/forms/{form_id}` — 양식 Schema
- `POST /api/eapproval/extract` — `{ "form_id", "document_text" }`
- `POST /api/eapproval/upload` — `file`, `form_id`

## 업로드 지원 범위

- PDF, JPG/JPEG/PNG/WEBP, XLS/XLSX, CSV/TXT, DOCX, HWPX를 지원합니다.
- 스캔 PDF와 이미지는 GPT Vision API 설정이 필요합니다.
- DOC와 HWP는 현재 안정적인 변환기가 없어 지원하지 않습니다.

## 테스트

서버를 실행한 뒤 양식을 선택하고 파일을 첨부하거나, AI 양식 추천 모드를 사용하세요.
