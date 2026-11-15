# 오늘,그리고 · AI

2026 AI 우왕톤 22팀 **NEAR**의 AI 서버입니다. 어린 사용자의 대화를 바탕으로 일기 작성을 돕고, 4컷 장면과 이미지를 생성하며, 우냥이 고민상담에 응답합니다.

[서비스 바로가기](https://today-and-near-team22.pages.dev/) · [시연 영상](https://www.youtube.com/watch?v=1aYGyOrBU4E) · [FE / 전체 프로젝트 소개](https://github.com/woowangthon/WOOWANGTHON_TEAM_22_FE) · [BE 저장소](https://github.com/woowangthon/WOOWANGTHON_TEAM_22_BE)

## 담당 기능

| 기능 | 구현 내용 |
| --- | --- |
| **AI 대화형 일기** | 빈 대화의 첫 질문, 대화 맥락에 따른 후속 질문과 종료 판단을 제공합니다. 대화 원문과 근거 번호를 연결한 일기 초안을 만들며, 확인이 필요한 결과로 BE에 전달합니다. |
| **4컷 장면·이미지** | 확인한 일기에서 장면 글과 근거를 구성하고 컷별 이미지를 생성합니다. 장면 계획의 형식·시간 제한 실패에는 허용된 경우 확인된 캡션을 사용하며, 이미 생성한 컷을 보존합니다. |
| **OCR·이미지 안정화** | RapidOCR·ONNX Runtime으로 이미지 속 문자를 탐지하고 좁은 문자 영역을 국소 복원합니다. 생성 원본을 먼저 캐시에 보관하고 생성 잠금을 해제한 뒤 OCR을 실행합니다. OCR 실패나 처리 시간 부족 시 원본을 유지합니다. |
| **우냥이 고민상담** | 일기와 별도로 전달된 고민 대화를 바탕으로 감정 표현과 다음 행동을 돕는 응답을 만듭니다. 종료 요청과 도움이 필요한 상황을 구분하고, 일시적인 모델 오류를 안내합니다. |
| **오류·결과 처리** | 입력 형식·출처·응답 구조를 검사하고 안전한 오류를 반환합니다. 공급자 오류, 생성 전 실패와 결과 불명을 구분해 BE가 저장·조회·재시도를 판단하도록 합니다. |

우냥이는 전문 심리치료나 진단을 제공하지 않습니다. 응답 생성은 AI가, 회원별 상담 보관·소유권·만료·이어쓰기 상태 관리는 BE가 담당합니다.

일기 초안 검사를 통과하지 못하면 아이의 원문을 사용하는 `fallback` 결과가 나올 수 있습니다. 생성 결과는 사용자가 확인해야 하며, 원문 근거 검사나 OCR이 모든 오류·이미지 문자를 제거한다고 보장하지 않습니다.

## BE와 연결되는 구조

```text
FE: 화면·입력·결과 확인
  ↓
BE: 회원 인증·대화 이력·작업 ID·DB/Storage 저장
  ↓ 필요한 이력·확인한 입력        ↑ 생성 결과 JSON
AI: 질문·초안·장면·이미지·우냥이 응답
  ↓
Groq / Cloudflare Workers AI / 선택형 OpenAI 공급자
```

AI API는 회원·날짜별 기록을 영구 저장하지 않습니다. BE가 각 요청에 필요한 대화 이력을 전달하며, AI 내부의 짧은 이미지 캐시는 영구 저장을 대신하지 않습니다. AI 서버는 BE가 접근하는 내부 서비스로 사용합니다.

| 메서드·경로 | 역할 |
| --- | --- |
| `GET /api/status` | 모드와 설정 존재 여부 확인. 키 유효성·실모델 성공 검사는 아닙니다. |
| `POST /api/chat` | 다음 일기 질문과 종료 여부 |
| `POST /api/diary` | 초안 글·원문 근거·페이지·확인 필요 여부 |
| `POST /api/visual-story` | 일기 기반 4컷 또는 그림책 장면 구성 |
| `POST /api/visual-story/image` | 확인한 장면의 이미지와 생성 상태 |
| `POST /api/worry/chat` | 우냥이 고민 대화 응답 |

개별 이미지 `/api/image`와 음성 전사·합성 `/api/transcribe`, `/api/speech`, `/api/voice-chat`도 AI 저장소에 있습니다. **공개 FE에서 음성 기능까지 연결되었다는 의미는 아닙니다.** 개발용 화면·설정은 [음성 안내](docs/VOICE_SETUP.md)를 참고하세요.

계약 참고: [AI API 규격](docs/API_CONTRACT.md) · [BE 현재 API·저장 계약](https://github.com/woowangthon/WOOWANGTHON_TEAM_22_BE#readme). 개별 과거 문서의 검증 결과와 현재 구현 범위는 구분합니다.

## 기술과 모델 설정

Python·FastAPI·Uvicorn·Pydantic, OpenAI 호환 SDK·HTTPX, Pillow, RapidOCR·ONNX Runtime, python-dotenv를 사용합니다. 정확한 패키지 버전은 [requirements.txt](requirements.txt)에 있습니다.

아래는 **현재 코드와 `.env.example`에 있는 기본/예시 설정**입니다. 실제 운영 환경의 모델명이나 성능을 확인한 목록이 아닙니다.

| 용도 | 공급자·설정 |
| --- | --- |
| 텍스트 대화·일기 | Groq, `GROQ_TEXT_MODEL` 예시 `openai/gpt-oss-20b` |
| 4컷 이미지 | Cloudflare Workers AI, `CLOUDFLARE_IMAGE_MODEL`의 `@cf/black-forest-labs/flux-1-schnell` |
| 4컷 그림용 장면 명세 | Cloudflare, `CLOUDFLARE_SCENE_MODEL` 예시 `@cf/meta/llama-3.3-70b-instruct-fp8-fast` |
| 선택형 이미지 검토·음성 | `VISION_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER`와 해당 모델 변수. 기본 TTS는 비활성입니다. |

`AI_MODE=openai`는 **실제 모델 호출 모드**라는 기존 계약명입니다. 공급자는 별도의 `TEXT_PROVIDER`·`IMAGE_PROVIDER` 등으로 선택하므로 이 값만으로 OpenAI 공급자를 사용한다고 판단하지 않습니다. 현재 Cloudflare 4컷 경로는 컷을 생성·보존하고 로컬 OCR을 수행하며, 모든 컷에 별도 비전 모델 검토를 수행하는 것은 아닙니다.

## 로컬 실행

Python 3.11 이상을 사용하는 개발 안내가 제공되어 있습니다. 아래는 AI 저장소 루트에서 실행하는 PowerShell 예시이며, 다른 환경은 [개발 환경 안내](docs/VSCODE_SETUP.md)를 참고하세요.

```powershell
git clone https://github.com/woowangthon/WOOWANGTHON_TEAM_22_AI.git
cd WOOWANGTHON_TEAM_22_AI
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
$env:AI_MODE = 'mock'
.\.venv\Scripts\python.exe server.py
```

이미 `.venv`와 `.env`가 있으면 재사용하고 덮어쓰지 않습니다. `server.py`는 **AI 저장소의 `.env`**를 읽으며, 같은 이름의 셸 환경변수가 있으면 그 값이 우선합니다. `.env.example`은 실제 호출 모드이므로 키 없이 확인할 때는 위처럼 `AI_MODE=mock`으로 명시하거나 `.env`의 값을 수정하세요.

- API 문서: `http://127.0.0.1:8002/docs`
- 상태: `http://127.0.0.1:8002/api/status`
- 기본 바인딩: `127.0.0.1`, 기본 포트: `8002`. 루트(`/`)에 앱 화면이 없어 404를 반환합니다.
- mock은 계약 확인용 고정 응답입니다. 실제 이미지·음성을 생성하거나 실제 모델 품질을 검증하지 않습니다. 로그인과 기록 저장은 별도로 실행한 BE·Supabase가 필요합니다.

실제 4컷의 로컬 OCR을 사용할 개발 환경은 의존성을 설치한 뒤 다음 명령으로 OCR 모델을 준비합니다. 최초 준비에는 모델 다운로드가 필요할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe prepare_ocr.py
```

### 필요한 환경변수

실제 호출을 사용할 때만 개발용 `.env`에 해당 공급자의 키와 설정을 입력하고 `AI_MODE`를 실제 호출 모드로 바꿉니다. 셸에 mock 값을 설정했다면 셸 값도 함께 변경해야 합니다. 실제 키·운영 환경값을 README나 Git에 넣지 않습니다.

| 환경변수 이름 | 용도 |
| --- | --- |
| `AI_MODE`, `PORT` | mock/실제 호출 모드, 로컬 포트 |
| `TEXT_PROVIDER`, `IMAGE_PROVIDER`, `VISION_PROVIDER`, `STT_PROVIDER`, `TTS_PROVIDER` | 기능별 공급자 선택 |
| `GROQ_API_KEY`, `GROQ_TEXT_MODEL`, `GROQ_VISION_MODEL`, `GROQ_STT_MODEL` | Groq 인증과 텍스트·검토·음성 인식 모델 |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Cloudflare Workers AI 계정과 호출 권한 |
| `CLOUDFLARE_IMAGE_MODEL`, `CLOUDFLARE_SCENE_MODEL`, `CLOUDFLARE_COMIC_REVIEW_MODEL` | 이미지·장면 명세·선택형 검토 설정. 검토 변수만으로 모든 생성 경로에서 검토가 켜지는 것은 아닙니다. |
| `OPENAI_API_KEY`, `OPENAI_TEXT_MODEL`, `OPENAI_IMAGE_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_STT_MODEL`, `OPENAI_TTS_MODEL`, `TTS_VOICE` | OpenAI 공급자를 선택한 기능의 인증·모델·음성 설정 |
| `WORRY_ENABLE_MODEL` | 우냥이 외부 모델 호출 활성화. BE의 `WORRY_ENABLED` 및 개발용 DB 준비와 별개입니다. |
| `ENABLE_VOICE_DEMO`, `ENABLE_WORRY_DEMO` | 선택형 localhost 개발 화면 |

전체 양식은 [.env.example](.env.example), 공급자별 설명은 [설정 안내](docs/MULTI_PROVIDER_SETUP.md)에 있습니다. AI 서비스 자체에는 사용자 인증이 없으므로 공개 FE가 직접 호출하는 서버로 사용하지 않습니다.

## 오류 처리와 생성 결과 보존

- API 입력 형식 오류와 공급자·모델 응답 오류를 구분하고, 공급자 원문이나 키·대화 내용을 오류 로그에 그대로 남기지 않습니다.
- 일기 결과의 `fallback`, `mock`, `requires_confirmation`을 함께 확인합니다. HTTP 성공만으로 실제 모델 생성이나 검토 통과를 판정하지 않습니다.
- 컷별 상태와 실제 이미지 유무를 확인하고, 일부 컷의 실패 때문에 기존 성공 컷을 폐기하지 않습니다. 시간 초과·응답 유실로 결과가 불명확하면 BE의 **기존 작업 ID 조회**로 확인하며 새 생성으로 자동 우회하지 않습니다.
- 생성 원본 캐시와 OCR 잠금을 분리하고, OCR의 ONNX 스레드를 제한합니다. 캐시는 메모리에 있으므로 재시작 후 모든 결과의 복구를 보장하지 않습니다. 영구 저장은 BE의 DB·Storage 책임입니다.
- 우냥이는 일시적 모델 실패 때 안내를 반환하고 대화를 이어갈 수 있도록 처리합니다. 실제 모델 응답의 공감·안전성·품질은 합성 테스트 통과와 별도로 평가해야 합니다.

## 파일 구조

| 경로 | 역할 |
| --- | --- |
| [server.py](server.py), [models.py](models.py), [visual_models.py](visual_models.py) | API, 입력·응답 계약 |
| [engine.py](engine.py), [prompts.py](prompts.py) | 일기 질문·초안 생성과 검증 |
| [visual_story.py](visual_story.py), [scene_prompting.py](scene_prompting.py), [comic_images.py](comic_images.py) | 장면 구성·그림 입력·컷별 생성과 캐시 |
| [providers.py](providers.py), [token_budget.py](token_budget.py), [diagnostics.py](diagnostics.py) | 공급자 연결·요청 예산·안전한 진단 |
| [image_quality.py](image_quality.py), [prepare_ocr.py](prepare_ocr.py) | 로컬 OCR과 문자 영역 처리·모델 준비 |
| [worry_support.py](worry_support.py) | 우냥이 대화·종료·도움 안내·오류 처리 |
| [voice.py](voice.py), [dev_voice.py](dev_voice.py) | 선택형 음성 기능·개발 화면 |
| [tests/](tests/), [scripts/](scripts/), [docs/](docs/) | 자동 검사·별도 검증 도구·계약과 검증 기록 |

## 테스트와 검증 범위

AI 루트의 개발 가상환경에서 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:AI_MODE = 'mock'
.\.venv\Scripts\python.exe -m pytest -q
```

| 검증 자료 | 확인 범위와 한계 |
| --- | --- |
| [tests/](tests/) | 일기·장면·공급자 계약·우냥이·OCR·잠금·캐시·오류 처리. 모델을 대체한 합성 응답과 로컬 처리를 검사합니다. |
| [2026-11-15 배포 비교](docs/DEPLOYMENT_SYNC_20261115.md) | 기존 검증 기록은 AI Python 303개, BE↔AI 교차 103개 통과입니다. 실제 로컬 OCR을 포함하지만 외부 공급자·DB는 합성 대역이며, 이번 README 작업에서 재실행한 결과가 아닙니다. |
| [2026-11-08 통합 검증](docs/INTEGRATION_VERIFICATION.md), [요구사항 재점검](docs/REQUIREMENTS_AUDIT.md) | 가상 입력으로 수행한 당시 실모델 호출·실패·fallback 기록입니다. 당시 모델·코드·입력의 결과이며 현재 운영 품질이나 전체 서비스 성공을 증명하지 않습니다. |

실제 모델 호출 검증은 별도의 키·사용량이 필요한 작업입니다. 처리 시간·성공률·품질 수치를 합성 테스트 결과에서 추정하지 않습니다.

### 일반 개발 실행과 Render 배포의 차이

Render는 별도 통합 저장소의 `runtime:create_runtime_app`과 OCR 사전 준비·worker·readiness 설정을 사용합니다. 이 AI 저장소의 일반 `server.py` 실행과 같지 않으며, Render 전용 `runtime.py`·`check_runtime.py`를 개발 기본 명령으로 요구하지 않습니다. 정확한 차이는 [배포 코드 비교](docs/DEPLOYMENT_SYNC_20261115.md)를 참고하세요. 실제 Render Live SHA는 미확인입니다.
