# 변수 및 함수 설명

코드 안의 `#` Python 주석도 함께 참고하세요. FE 상태 변수와 저장용 변수는 포함하지 않습니다. 아래는 다른 개발자가 연동하거나 동작을 바꿀 때 확인할 변수입니다.

## 서버 설정 (.env)

| 변수 | 기본값/자료형 | 역할 |
|---|---|---|
| `OPENAI_API_KEY` | 문자열, 필수 | 서버에서만 사용하는 API 인증 키 |
| `AI_MODE` | `openai` / `mock` | 실제 AI 호출 또는 고정 응답 체험 |
| `TEXT_MODEL` | `gpt-4.1-mini` | 질문·일기 생성과 검토 모델 |
| `IMAGE_MODEL` | `gpt-image-1.5` | 페이지 그림 생성 모델 |
| `PORT` | `8002` | 로컬 서버 포트 |
| `BASE_DIR` | Path | 서버 파일이 위치한 폴더 |

## API 자료 구조 (models.py)

| 변수/필드 | 자료형 | 의미 |
|---|---|---|
| `messages` | Message 배열 | 시간순 전체 대화, 최대 60개 |
| `role` | `child` / `assistant` | 아이 발언인지 AI 질문인지 구분 |
| `text` | 문자열 | 메시지, 문장 또는 페이지의 실제 글 |
| `question` | 문자열 | 다음에 화면에 표시할 AI 발화 |
| `finished` | bool | 아이가 대화 종료를 표현했는지 여부 |
| `sentences` | Sentence 배열 | 생성한 일기 문장들 |
| `source_ids` | 정수 배열 | 문장을 뒷받침하는 아이 발언의 전체 대화 내 위치 |
| `accepted` | bool | 별도 모델 검토가 후보를 허용했는지 여부 |
| `confirmed` | bool | 이미지 요청 전 글을 확인했다는 표시 |

## 생성 엔진 (engine.py)

| 변수 | 역할 |
|---|---|
| `adapter` | OpenAI 통신 담당 객체. 테스트에서는 가짜 객체로 교체 |
| `mock` | 실제 API 없이 고정 응답을 사용하는지 여부 |
| `client`, `api_key` | OpenAI 클라이언트와 서버 인증 키 |
| `instruction`, `payload`, `schema` | 모델 지침, 입력 자료, 응답 자료형 |
| `response`, `result` | API에서 받은 결과 |
| `conversation` | 모델에 전달할 전체 대화 사전 배열 |
| `child_messages` | 질문 생성 시 아이 발언이 있는지 확인하는 목록 |
| `examples` | 체험 모드의 고정 질문 목록 |
| `candidate` | 아직 검토하지 않은 질문 또는 일기 초안 |
| `review`, `accepted`, `valid` | 검토 결과와 형식/근거 검사 통과 여부 |
| `sources` | 아이 발언만 추린 `{id, text}` 목록 |
| `allowed_ids` | 근거로 사용할 수 있는 아이 발언 번호 집합 |
| `fallback` | 검사를 통과하지 못해 안전한 질문/원문을 사용했는지 표시 |
| `sentences` | 최종 일기 문장과 각 문장의 근거 번호 |
| `page_size`, `start`, `group` | 최대 6페이지로 나누는 묶음 크기·시작 위치·문장 묶음 |
| `pages` | `{text, source_ids, imageUrl}` 페이지 배열 |
| `image_url` / `imageUrl` | 생성 그림의 PNG 데이터 URL. 없으면 null |
| `requires_confirmation` | 결과가 사용자 확인 대상임을 표시 |
| `rejected` | 이미지 검토에서 거절되어 그림을 반환하지 않았는지 표시 |

`CHAT_PROMPT`/`CHAT_REVIEW`는 질문 생성/검토 지침, `DIARY_PROMPT`/`DIARY_REVIEW`는 일기 생성/검토 지침, `IMAGE_PROMPT`/`IMAGE_REVIEW`는 그림 생성/검토 지침입니다. 모두 prompts.py에서 수정합니다.

## API 서버 변수 및 응답 자료형

| 이름 | 역할 |
|---|---|
| `app` | AI 전용 FastAPI 서버 객체 |
| `engine` | 생성 로직 객체. 테스트에서는 모델 대체 객체를 주입 |
| `mode` | AI_MODE 값을 확인하는 지역 변수 |
| `body` | 검증된 BE 요청 본문 |
| `request`, `error` | 오류 처리 함수에 전달되는 요청과 오류 |
| `StatusResponse` | mode/configured 응답 규격 |
| `QuestionResponse` | question/finished/mock/fallback 응답 규격 |
| `Source`, `Page`, `DiaryResponse` | 근거 발언, 장면 글, 일기 결과 규격 |
| `ImageResponse` | 그림 데이터와 검토 상태 응답 규격 |

## 주요 함수

| 함수 | 역할 |
|---|---|
| `create_app()` | AI API 및 오류 처리 등록 |
| `OpenAIAdapter.parse()` | 자료형을 지정해 OpenAI 응답 생성 |
| `OpenAIAdapter.image()` | 그림 생성 및 검토 |
| `DiaryEngine.conversation_data()` | 메시지 직렬화와 총 길이 검사 |
| `DiaryEngine.next_question()` | 첫 질문 또는 전체 맥락 기반 후속 질문 |
| `DiaryEngine.make_diary()` | 근거 검사 후 일기와 장면 글 반환 |

반복문 임시 변수 `message`, `item`, `source`, `sentence`는 현재 처리 중인 메시지/항목/근거/문장입니다. `index`, `sid`는 메시지 위치와 근거 번호입니다. 이 서비스에는 사용자 ID, 날짜, DB 연결, 화면 상태 변수가 없습니다.

## 음성 기능 추가 변수 (voice.py / models.py)

| 이름 | 의미 |
|---|---|
| `STT_MODEL` | 음성 인식 모델. 기본 gpt-transcribe |
| `TTS_MODEL` | 문장을 읽는 음성 합성 모델. 기본 gpt-4o-mini-tts |
| `TTS_VOICE` | 기본 제공 목소리 이름. 기본 coral |
| `MAX_AUDIO_BYTES` | 업로드 음성 최대 크기, 8×1024×1024바이트 |
| `AUDIO_TYPES` | 허용 확장자와 MIME의 대응표 |
| `voice_service` | 기존 DiaryEngine을 공유하는 음성 처리 객체 |
| `audio_bytes` | 처리 중인 음성 바이너리 |
| `extension`, `mime_type` | 파일 형식을 검사하고 모델에 전달하는 값 |
| `transcript` | 음성에서 인식한 글의 초안 |
| `question_result` | 기존 대화 엔진에서 생성·검사한 질문 |
| `audio_base64` | MP3를 JSON에 담기 위해 base64로 변환한 문자열 |
| `audio_mime_type` | 반환 음성 형식 audio/mpeg |
| `audio_error` | 질문은 성공했으나 음성만 실패했거나 mock일 때의 안내 |
| `SpeechRequest` | 음성으로 읽을 text 입력 자료형 |
| `TranscriptionResponse` | 전사 초안·확인 필요 여부 응답 자료형 |
| `VoiceReplyResponse` | QuestionResponse에 음성 필드를 추가한 응답 자료형 |

`VoiceService.transcribe()`는 음성→글, `speech()`는 글→MP3, `reply()`는 질문 생성 후 음성 합성을 수행합니다. `require_live_mode()`는 mock에서 실제 음성 처리처럼 보이는 응답을 막습니다. 이 변수들은 화면의 마이크 상태나 DB 저장 변수가 아닙니다.
