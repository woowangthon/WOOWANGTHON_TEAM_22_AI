# 기존 AI 저장소에 음성 기능 추가하기

이 버전은 AI 서버만 포함합니다. 내장 마이크를 직접 켜는 버튼은 FE 담당자가 구현합니다. 여기서는 마이크 녹음 파일의 음성 인식과 AI 질문의 음성 합성을 제공합니다. FE/BE가 연결되기 전에는 /docs에서 파일을 선택해 시험합니다.

## 어떤 방식인가요?

```text
대화 시작
 → BE가 AI /api/voice-chat에 빈 messages 전달
 → AI가 첫 질문 글 + MP3 반환
 → FE가 질문을 보여주고 읽어 줌
 → 아이가 녹음 시작 버튼을 누르고 말함
 → 녹음 종료 후 FE → BE → AI /api/transcribe
 → 인식한 글을 FE에서 확인·수정
 → BE가 확정된 글을 기존 대화에 추가
 → AI /api/voice-chat에 전체 대화 전달
 → 다음 질문 글 + MP3 반환 → 반복
 → '이제 그림책으로 일기 보기' → 기존 /api/diary
```

아이의 발언을 AI가 추측하지 않도록, 전사 초안을 확인한 뒤 대화에 추가하는 흐름입니다. AI는 인식 결과가 실제 발언과 완전히 같은지 보장할 수 없습니다. 무음에서도 모델이 잘못된 글을 만들 수 있으므로 화면에서 원문을 확인할 수 있어야 합니다.

이번 버전은 발화마다 녹음을 끝내서 보내는 방식입니다. 자동 침묵 감지, 계속 듣기, 중간 말 끊기, 실시간 양방향 스트리밍은 포함하지 않습니다. 음성 재생이 끝나기 전에는 녹음을 시작하지 않도록 FE에서 제어합니다.

## VS Code에 적용

1. 실행 중인 AI 서버 터미널에서 Control+C를 누릅니다.
2. ZIP을 풀고 `ai-repo-voice` 안의 내용물을 기존 AI 저장소 루트에 복사합니다.
3. 기존에 수정한 파일은 비교 후 병합합니다. `.git`, 개인 `.env`, `.venv`는 덮어쓰지 않습니다. 새 `voice.py`, `tests/test_voice.py`, 이 문서와 FE_BE_VOICE.md를 추가합니다. server.py/models.py/requirements.txt 및 기존 테스트·문서는 새 버전 변경을 반영합니다.
4. VS Code 터미널에서 실행합니다.

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell에서는 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`를 사용합니다.

5. 기존 `.env`에서 API 키는 유지하고 아래 설정을 추가/수정합니다. 같은 이름을 여러 줄 중복 작성하지 마세요.

```dotenv
AI_MODE=openai
STT_MODEL=gpt-transcribe
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=coral
```

`OPENAI_API_KEY`도 설정되어 있어야 합니다. 키는 이 문서나 Git에 적지 않습니다. gpt-transcribe는 확인한 공식 문서의 전사 모델이며 계정의 모델 사용 권한을 확인해야 합니다. TTS 목소리는 이 기본 제공 목소리 설정을 사용하며 부모 목소리를 복제하지 않습니다.

6. 저장하고 서버를 다시 실행합니다.

```sh
python server.py
```

7. http://127.0.0.1:8002/docs 를 새로고침합니다. `/api/transcribe`, `/api/speech`, `/api/voice-chat`가 추가되어 있어야 합니다. 안 보이면 다른 폴더/기존 서버가 실행 중인지 확인하세요.

## 1. 질문 음성 만들기

`POST /api/speech → Try it out`에서 다음 JSON을 실행합니다.

```json
{"text":"오늘은 무슨 일이 있었어?"}
```

성공하면 HTTP 200, Content-Type audio/mpeg인 MP3 응답을 받습니다. /docs 버전에 따라 재생기 또는 다운로드 링크가 표시될 수 있습니다. 시험 화면에서 재생이 어려우면 터미널로 시험할 수 있습니다(유료 호출 1회).

```sh
curl --fail-with-body -X POST http://127.0.0.1:8002/api/speech \
  -H 'Content-Type: application/json' \
  -d '{"text":"오늘은 무슨 일이 있었어?"}' \
  --output /tmp/ai-question.mp3
```

오류 없이 완료된 경우에만 macOS에서 다음을 실행합니다.

```sh
open /tmp/ai-question.mp3
```

오류 상태라면 이 파일이 MP3 대신 오류 JSON일 수 있으므로 오류 응답부터 확인하세요.

## 2. 아이의 음성을 글로 바꾸기

개발 시험에는 본인이 말한 가상의 하루 이야기 녹음을 사용하세요.

1. 짧은 한국어 녹음 파일(m4a/mp4/webm/wav/mp3 등)을 준비합니다.
2. `/api/transcribe → Try it out → file`에서 파일을 선택합니다.
3. Execute를 누르면 `text`에 전사 초안이 반환됩니다.
4. 잘못 인식된 부분은 확인 후 고쳐서 다음 요청에 사용합니다.

`/docs`에는 직접 마이크를 녹음하는 버튼이 없습니다. 앱의 마이크 버튼은 FE에서 별도로 연결해야 합니다. 전체 파일은 8 MiB 이내이며 한 번에 약 30~60초의 짧은 발화로 시작하는 것을 권장합니다. 서버가 길이(초)를 검사하는 것은 아니고 바이트 수를 제한합니다.

## 3. 대화를 이어서 질문을 음성으로 받기

`POST /api/voice-chat → Try it out`에서 실행합니다.

```json
{
  "messages": [
    {"role":"assistant","text":"오늘은 무슨 일이 있었어?"},
    {"role":"child","text":"오늘 친구랑 공놀이를 했어."}
  ]
}
```

`question`에 다음 질문, `audio_base64`에 MP3 데이터가 반환됩니다. 이 필드는 파일 주소가 아닌 데이터이므로 주소창에 붙이지 않습니다. FE/BE 담당자가 MP3로 변환해 재생합니다. 구조화된 예시는 API_CONTRACT.md를 참고하세요.

`audio_error`가 있고 `question`은 있다면 질문은 성공하고 음성만 실패한 것입니다. 질문을 다시 생성하지 않고 그 문장으로 `/api/speech`만 재시도합니다.

## mock 모드와 검사

mock에서 `/api/voice-chat`은 고정 질문과 `audio_base64:null`을 반환합니다. `/api/transcribe`, `/api/speech`는 503으로 실제 음성 기능이 비활성화됐음을 알립니다. 녹음 내용을 듣지 않고 가짜 전사나 가짜 음성을 반환하지 않습니다.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

외부 API를 대체한 34개 검사를 통과했습니다. 실제 마이크 장치, 음성 인식 정확도, 한국어 음성 품질, 계정별 모델 접근은 실제 키와 FE 화면으로 추가 검증해야 합니다.

공식 참고: [음성 인식](https://developers.openai.com/api/docs/guides/speech-to-text), [음성 합성](https://developers.openai.com/api/docs/guides/text-to-speech).
