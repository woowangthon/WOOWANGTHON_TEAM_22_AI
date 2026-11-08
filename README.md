# AI 전용 레포지토리 — 음성·4컷 지원 v1.2

음성 전사와 음성 응답을 지원하며, 텍스트 대화를 바탕으로 다음 질문, 일기 초안, 그림책 장면 글 및 그림을 생성하는 Python 서비스입니다. FE 화면, 사용자 계정, DB, 날짜별 저장 기능은 포함하지 않습니다.

음성 기능을 기존 코드에 적용하려면 **docs/VOICE_SETUP.md**부터 읽으세요. 마이크 녹음·재생은 FE에서 연결해야 하며 이 패키지의 /docs에는 녹음 버튼이 없습니다.

## 담당 범위

```text
FE (화면·입력·버튼·그림책 표시)
 ↓ 요청 / ↑ 결과
BE (인증·대화 이력·일기 날짜·DB·이미지 저장)
 ↓ 전체 대화 / ↑ 생성 결과 JSON
AI (이 저장소: 질문·일기·그림 생성 및 검토)
 ↓ 모델 요청 / ↑ 모델 응답
Groq / Cloudflare / 선택적 OpenAI API
```

AI의 `server.py`는 AI 기능을 BE에 제공하는 통신 창구입니다. 별도의 BE 레포지토리에서 담당하는 회원/일기 관리 서버와는 역할이 다릅니다. AI 서비스는 이전 요청을 기억하거나 일기를 저장하지 않으므로 BE가 매번 전체 대화를 전달해야 합니다.

| 파일 | 역할 |
|---|---|
| `server.py` | AI API 경로, 요청 검사, 오류 처리 |
| `voice.py` | 음성 전사, 음성 합성, 음성 질문 응답 |
| `engine.py` | 모델 호출, 질문·일기·그림 생성, 결과 검사 |
| `prompts.py` | 대화 방식과 원문 보존 규칙 |
| `models.py` | BE↔AI 요청/응답 자료형 |
| `.env.example` | 개인 설정의 빈 양식 |
| `requirements.txt` | 실행에 필요한 패키지 |
| `requirements-dev.txt`, `pytest.ini`, `tests/` | 개발 시 자동 검사 |
| `docs/VSCODE_SETUP.md` | 기존 Git 저장소에 적용하는 순서 |
| `docs/API_CONTRACT.md` | BE 담당자에게 전달할 API 규격 |
| `docs/VARIABLES.md` | 변수·함수 설명 |

## 먼저 실행해 보기

Python 3.11 이상을 사용합니다. 상세한 Windows/macOS 안내는 `docs/VSCODE_SETUP.md`에 있습니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`의 `AI_MODE=mock`으로 설정하면 키 없이 연결을 시험할 수 있습니다.

```sh
python server.py
```

개발용 API 문서: http://127.0.0.1:8002/docs
서버 상태: http://127.0.0.1:8002/api/status

루트 주소(`/`)는 404가 정상입니다. 앱 화면이 없기 때문입니다. `/docs`는 API 확인 도구이며 FE 제품 화면이 아닙니다.

실제 호출은 `AI_MODE=openai`로 켭니다(이 값은 공급자명이 아닌 실제 호출 모드입니다). 기본 텍스트는 `TEXT_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_TEXT_MODEL=openai/gpt-oss-20b`를 사용합니다. 이미지는 Cloudflare 생성과 Groq 검토를 사용하며, 전체 설정은 [.env.example](.env.example)과 [공급자 안내](docs/MULTI_PROVIDER_SETUP.md)를 따릅니다. 실제 키는 `.env`에만 보관합니다.

## 남겨 둔 AI 기능

- 빈 대화에서 첫 질문 반환
- 아이의 답변과 전체 맥락에 따른 한 개의 후속 질문
- 원문 근거 번호를 포함하는 일기 초안 및 최대 6개 장면 글
- 확인한 장면 글을 바탕으로 그림 생성 및 검토
- 검사를 통과하지 못한 일기 초안은 아이 원문으로 대체

`mock`은 정해진 질문과 원문을 반환하는 연결 시험 모드입니다. 실제 AI의 품질을 검증하는 모드가 아니며 그림·음성을 생성하거나 음성을 인식하지 않습니다.

## 검증과 개발 범위

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

이 패키지는 모델을 대체한 자동 검사를 포함합니다. 실제 API 호출과 생성 품질은 본인 키로 추가 확인해야 합니다. AI 검토로 추측이나 환각이 완전히 사라지는 것은 아니므로 결과의 사용자 확인 절차는 FE와 BE에서 구현해야 합니다.

개발 기본값은 로컬 PC의 127.0.0.1에만 연결됩니다. CORS 및 FE 직접 호출 경로, 서비스 인증은 구현하지 않았습니다. CORS는 접근 제어 장치가 아니므로 배포 시 AI 서버를 BE 전용 내부 네트워크에 두고 서비스 간 인증·호출 제한을 추가해야 합니다. AI 저장소에 사용자 로그인 기능을 넣을 필요는 없습니다.

실제 아동의 데이터 사용 전에는 보호자 동의와 적용되는 아동 데이터 처리 요건을 검토하세요. 개발 단계에서는 가상의 대화를 사용합니다. `store=False`가 계정의 Zero Data Retention 설정을 대신하지 않습니다. 첫 질문 외의 AI 대화에는 생성과 검토 호출 비용이 발생하고, 그림 요청은 별도 비용이 발생합니다.

구조화된 응답 구현 참고: [OpenAI 공식 Structured Outputs 문서](https://developers.openai.com/api/docs/guides/structured-outputs).

통합 검증 실행법과 실제 호출 결과는 [통합 검증 보고서](docs/INTEGRATION_VERIFICATION.md)를 참고하세요.

최신 요구사항별 구현 상태와 보완 사항: [요구사항 재점검](docs/REQUIREMENTS_AUDIT.md).
