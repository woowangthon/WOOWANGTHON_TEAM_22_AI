# 기능별 AI 연결 및 실행 안내

현재 구현은 성인 개발자의 예시 문장·녹음으로 개발과 시연을 하기 위한 설정입니다. 실제 아동에게 제공할 때의 서비스 약관·연령 조건과 데이터 처리 조건은 별도로 확인해야 합니다.

## 1. 구현한 기능

| 기능 | 기본 공급자 / 모델 | 필요한 설정 |
| --- | --- | --- |
| 다음 질문·일기 정리·장면 묶기 | Groq / openai/gpt-oss-20b | GROQ_API_KEY |
| 음성 인식 | Groq / whisper-large-v3-turbo | 같은 GROQ_API_KEY |
| 그림 생성용 영문 묘사 | Groq / 위 텍스트 모델 | 같은 GROQ_API_KEY |
| 그림책·만화 단일 장면 이미지 | Cloudflare / FLUX.1 schnell | CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID |
| 생성 이미지와 원문 비교 | Groq / qwen/qwen3.8-27b | 같은 GROQ_API_KEY |
| 한국어 음성 출력 | 기본 꺼짐 / 선택 시 OpenAI TTS | 사용 가능한 OPENAI_API_KEY와 TTS_PROVIDER=openai |

이미지 생성은 장면 글을 확인한 후에만 가능합니다. 생성 묘사는 영문으로 압축하지만 표시할 일기·캡션은 원문을 유지합니다. 생성한 그림을 원문과 자동 비교하고 거절되면 imageUrl을 반환하지 않습니다. 자동 검토가 사실 일치를 보장하지 않으므로 최종 사용자 확인도 유지합니다.

무료 사용 한도는 공급자와 모델마다 다릅니다. 질문 한 번은 생성+검토로 보통 Groq 요청 두 번입니다. 그림 한 장은 Groq 묘사 한 번+Cloudflare 생성 한 번+Groq 이미지 검토 한 번입니다. 자동 재시도나 다른 유료 공급자로의 자동 전환은 없습니다.

## 2. 필요한 키 발급

### Groq

1. <https://console.groq.com/keys>에 로그인합니다.
2. API 키를 만들어 로컬 .env의 GROQ_API_KEY에 입력합니다.
3. <https://console.groq.com/settings/limits>에서 계정에 표시된 모델과 호출 한도를 확인합니다.

이름에 openai/gpt-oss가 들어가도 Groq에서 제공하는 모델입니다. 이 경로에는 OpenAI 키가 아닌 Groq 키를 사용합니다.

### Cloudflare

1. <https://dash.cloudflare.com/>에서 사용할 계정을 선택합니다.
2. Workers AI 화면에서 Use REST API를 선택합니다.
3. Create a Workers AI API Token으로 전용 토큰을 발급합니다.
4. 토큰을 CLOUDFLARE_API_TOKEN에 입력합니다.
5. 같은 계정의 32자리 Account ID를 CLOUDFLARE_ACCOUNT_ID에 입력합니다.

계정 ID는 도메인 Zone ID가 아닙니다. 별도 Worker 배포는 필요 없으며 Python AI 서버에서 REST API를 직접 호출합니다. API 토큰은 해당 계정의 Workers AI에 한정하세요. 수동 토큰을 만든다면 공식 REST 안내의 Workers AI Read/Edit 권한을 확인하세요.

### OpenAI (선택)

잔액이 없는 기존 OpenAI 키는 필수가 아닙니다. 기본 TTS_PROVIDER=disabled를 유지하면 OpenAI로 요청하지 않습니다. 음성 출력을 켜려면 API 잔액·권한이 있는 키를 설정하고 TTS_PROVIDER=openai로 바꿉니다.

## 3. .env 설정

기존 .env를 덮어쓰지 말고 아래 항목을 추가하거나 수정하세요. 같은 변수 이름을 여러 줄에 중복 작성하지 마세요. .env.example에는 전체 설정 예시가 있고 실제 키는 들어 있지 않습니다.

```dotenv
AI_MODE=openai
PORT=8002
TEXT_PROVIDER=groq
STT_PROVIDER=groq
IMAGE_PROVIDER=cloudflare
VISION_PROVIDER=groq
TTS_PROVIDER=disabled
GROQ_API_KEY=여기에_Groq_키
CLOUDFLARE_API_TOKEN=여기에_Cloudflare_토큰
CLOUDFLARE_ACCOUNT_ID=여기에_32자리_계정_ID
```

GROQ_TEXT_MODEL, GROQ_STT_MODEL, GROQ_VISION_MODEL, CLOUDFLARE_IMAGE_MODEL은 .env.example의 기본값을 사용하세요. 과거 TEXT_MODEL, IMAGE_MODEL, STT_MODEL은 Groq/Cloudflare 선택 시 사용되지 않습니다. Groq 또는 Cloudflare 키 하나만 준비되면 해당 기능부터 시험할 수 있습니다. 그림은 두 서비스가 모두 필요합니다.

## 4. VS Code 실행

AI 저장소를 연 VS Code 터미널에서 실행합니다.

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python check_setup.py
```

check_setup.py는 키 존재 여부만 출력하며 키 값·잔액을 출력하지 않고 API도 호출하지 않습니다.

기존 서버를 Shift+F5 또는 실행 중인 터미널의 Control+C로 종료한 뒤, F5 → AI 서버: 실제 AI (.env 설정)을 선택합니다. 터미널 실행을 선택하면 아래 명령을 사용하고 F5를 중복 실행하지 마세요.

```bash
python server.py
```

<http://127.0.0.1:8002/docs>에서 시험합니다. .env를 변경한 뒤에는 서버를 재시작하세요. 키 교체 시 이전 프로세스의 클라이언트는 이전 키를 계속 사용할 수 있습니다.

## 5. 단계별 테스트

### 텍스트

POST /api/chat → Try it out → 아래 내용을 입력 → Execute.

```json
{
  "messages": [
    {"role": "assistant", "text": "오늘은 무슨 일이 있었어?"},
    {"role": "child", "text": "오늘 친구랑 공놀이를 했어."}
  ]
}
```

question에 후속 질문, mock에 false가 나오면 실제 텍스트 요청 성공입니다. messages가 빈 배열이면 고정 첫 질문만 반환하므로 API 연결 검사가 아닙니다.

POST /api/diary에 같은 전체 대화를 보내면 text와 pages를 반환합니다. 아이가 말하지 않은 사건·감정을 넣지 않았는지 확인합니다.

### 음성 입력

Mac QuickTime Player에서 새로운 오디오 녹음 → 내장 마이크 선택 → 성인 팀원이 예시 문장을 녹음 → .m4a로 저장합니다. POST /api/transcribe에서 파일을 선택해 업로드합니다. text를 확인·수정한 뒤 child 메시지로 사용합니다. 최대 8 MiB입니다. 마이크 제어는 FE가 담당하며 /docs에서는 녹음 파일 업로드로 시험합니다.

POST /api/voice-chat은 음성 파일을 받는 API가 아닙니다. 확인한 텍스트 messages를 받습니다. TTS_PROVIDER=disabled이면 question은 반환하고 audio_base64=null, audio_error에 비활성화 안내를 반환하는 것이 정상입니다. POST /api/speech는 이 설정에서 503을 반환합니다. 한국어 자동 음성 재생은 현재 무료 기본 구성에 포함하지 않았습니다. FE의 기기 음성 합성으로 연결하거나 OpenAI TTS를 켤 수 있습니다.

### 그림책·4컷

1. POST /api/visual-story에 아래 입력을 보냅니다.

```json
{
  "diary_text": "친구와 공놀이를 했다. 즐거웠다.",
  "confirmed": true,
  "format": "both"
}
```

2. 응답의 diary_hash와 원하는 scene의 source_ids를 복사합니다.
3. POST /api/visual-story/image에 아래 입력을 보냅니다. diary_hash는 예시 문구 대신 실제 응답의 64자리 값을 넣습니다.

```json
{
  "diary_text": "친구와 공놀이를 했다. 즐거웠다.",
  "diary_hash": "앞_단계에서_받은_64자리_값",
  "source_ids": [0],
  "format": "storybook",
  "confirmed": true
}
```

4. status=generated이면 imageUrl을 FE의 img src로 표시합니다. data:image/jpeg;base64 또는 data:image/png;base64 형식입니다. /docs JSON 자체는 그림을 표시하지 않습니다.
5. rejected는 원문 일치 검토에서 거절된 상태, failed는 생성/검토 실패 상태입니다. HTTP 200이어도 status와 error를 확인하세요. captions는 계속 유지됩니다.
6. comic4의 반복 컷에는 reuse_scene_id가 있습니다. 같은 그림을 재사용하고 중복 생성하지 마세요. 4컷 배치는 FE, 이미지 파일 저장은 BE가 담당합니다.

## 6. 변수와 개발자 참고

| 변수 | 의미 |
| --- | --- |
| TEXT_PROVIDER / STT_PROVIDER | 텍스트 / 음성 인식 공급자: groq 또는 openai |
| IMAGE_PROVIDER | cloudflare 또는 openai |
| VISION_PROVIDER | 이미지 검토 공급자: groq 또는 openai |
| TTS_PROVIDER | disabled 또는 openai |
| GROQ_API_KEY | Groq 전용 비밀 키 |
| GROQ_TEXT_MODEL | 대화·일기·이미지 묘사 모델 |
| GROQ_STT_MODEL | 한국어 녹음 인식 모델 |
| GROQ_VISION_MODEL | 생성 이미지 원문 일치 검토 모델 |
| CLOUDFLARE_API_TOKEN | Workers AI 토큰 |
| CLOUDFLARE_ACCOUNT_ID | 토큰과 같은 계정의 ID |
| CLOUDFLARE_IMAGE_MODEL | 현재 구현은 FLUX.1 schnell 전용 |
| OPENAI_API_KEY | OpenAI 기능을 선택했을 때만 필요한 키 |
| OPENAI_TEXT_MODEL / OPENAI_STT_MODEL | OpenAI 선택 시 텍스트 / STT 모델 |
| OPENAI_IMAGE_MODEL / OPENAI_VISION_MODEL | OpenAI 선택 시 생성 / 이미지 검토 모델 |
| OPENAI_TTS_MODEL / TTS_VOICE | OpenAI 음성 모델 / 목소리 |
| AI_MODE | mock은 외부 호출 없음, openai는 실제 호출 모드라는 기존 이름 |
| PORT | 서버 포트. 기본 8002 |

providers.py의 ProviderRouter가 공급자 선택과 키 분리, 요청 형식, 공개 가능한 오류 안내를 담당합니다. engine.py는 대화·일기 근거 검사, voice.py는 전사 확인·부분 실패, visual_story.py는 원문 장면·이미지 검토 흐름을 유지합니다.

기존 9개 API 주소와 JSON 필드는 유지합니다. /api/status의 mode=openai는 이전 계약을 유지하기 위한 실제 호출 모드 이름입니다. Groq를 사용해도 같은 값이 나오며 configured는 선택한 텍스트 공급자의 키 존재 여부입니다. 모든 기능의 권한·잔액이 정상이라는 뜻이 아닙니다.

FE: 마이크 녹음, 전사 수정·확인, 캡션 확인, 이미지/4컷 배치, 오디오 재생을 담당합니다. BE: 사용자 인증, 대화 이력, 날짜별 저장·조회, 이미지 영구 저장을 담당합니다. AI 서버는 여전히 상태를 저장하지 않으며 요청마다 전체 대화가 필요합니다.

## 7. 공식 참고 자료

- Groq 구조화 응답: <https://console.groq.com/docs/structured-outputs>
- Groq 음성 인식: <https://console.groq.com/docs/speech-to-text>
- Groq 이미지 검토: <https://console.groq.com/docs/vision>
- Groq 무료 한도: <https://console.groq.com/docs/rate-limits>
- Cloudflare 토큰 발급: <https://developers.cloudflare.com/workers-ai/get-started/rest-api/>
- FLUX.1 schnell 입력/출력: <https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/>
- Cloudflare 무료 사용량: <https://developers.cloudflare.com/workers-ai/platform/pricing/>

새 Groq·Cloudflare 자격 증명이 없으므로 실제 무료 계정 호출, 한국어 인식 품질, 실제 이미지 품질은 아직 검증하지 않았습니다. 테스트는 가짜 네트워크로 요청 규격·키 분리·원문 유지·실패 처리를 검사합니다.
