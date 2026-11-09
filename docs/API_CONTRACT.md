> 기능별 공급자 연결과 키 설정: [MULTI_PROVIDER_SETUP.md](MULTI_PROVIDER_SETUP.md). `/api/status`의 `mode=openai`는 기존 실제 호출 모드 이름이며 Groq를 선택해도 유지됩니다. `configured`는 선택한 텍스트 공급자의 키 존재 여부입니다.

# BE → AI 연동 규격 v1.1

기본 개발 주소는 `http://127.0.0.1:8002`입니다. POST 요청은 `Content-Type: application/json`으로 전송합니다. 기존 전체 예제의 `/api/chat`, `/api/diary`, `/api/image` 경로를 유지했습니다. `/question`, `/story`는 제공하지 않습니다.

## 책임 분리

| 동작 | FE | BE | AI |
| --- | --- | --- | --- |
| 대화 시작 | 화면 진입 | 빈 대화로 AI 요청, 응답 보관 | 첫 질문 반환 |
| 아이 답변 | 입력·전송 | 접근 권한 확인, 순서가 유지된 전체 대화 전달 | 후속 질문 생성 |
| 일기 버튼 | 버튼 표시·클릭 | 전체 대화로 일기 요청 | 일기·장면 글 생성 및 검사 |
| 그림 생성 | 글 확인 UI | 확인된 글만 요청 | 그림 생성·검토 |
| 결과 확정 | 글·그림 확인/수정 | 확정 상태와 결과 저장 | DB 작업 없음 |
| 날짜별 기록 | 달력·목록·상세 화면 | 날짜·사용자별 조회 및 보관 | 관여하지 않음 |

페이지 글을 나누는 것은 생성 콘텐츠 구성입니다. 글꼴, 페이지 넘김, 버튼, 그림 배치 등은 FE가 담당합니다. AI 응답의 `imageUrl`은 데이터 URL이며 저장소 주소가 아닙니다. BE가 필요에 따라 바이너리로 변환해 이미지 저장소에 저장하고 FE용 URL을 반환합니다.

## GET /api/status

```json
{"mode":"mock","configured":true}
```

`mode`는 mock/openai, `configured`는 mock이거나 API 키 문자열이 설정되었는지 여부입니다. 실제 모델 권한·결제·연결 상태를 검증하지는 않습니다.

## POST /api/chat

첫 질문 요청:

```json
{"messages":[]}
```

응답 예:

```json
{"question":"오늘은 무슨 일이 있었어?","finished":false,"mock":true,"fallback":false}
```

다음 질문 요청:

```json
{
  "messages": [
    {"role":"assistant","text":"오늘은 무슨 일이 있었어?"},
    {"role":"child","text":"친구와 공놀이를 했어."}
  ]
}
```

BE는 응답 question을 assistant 메시지로 보관하고, 다음 아이의 답변을 child 메시지로 추가하여 다시 전체 배열을 전달합니다. 서버는 세션을 기억하지 않으며 모델 지침은 서버의 prompts.py에 고정되어 있습니다.

`finished=true`는 종료 의사에 대한 신호입니다. FE에서 계속 질문을 강요하지 않고 일기 버튼을 안내합니다. 자동 일기 생성/저장을 의미하지 않습니다. `fallback=true`는 검토를 통과하지 못해 기본 질문으로 대체했다는 뜻입니다.

## POST /api/diary

요청 구조는 /api/chat과 같습니다. 예를 들어 다음 대화로 요청합니다.

```json
{
  "messages": [
    {"role":"assistant","text":"오늘은 무슨 일이 있었어?"},
    {"role":"child","text":"친구와 공놀이를 했어."},
    {"role":"assistant","text":"그때 어떤 기분이 들었어?"},
    {"role":"child","text":"즐거웠어."}
  ]
}
```

실제 AI 모드의 가능한 응답 예시(문구와 페이지 수는 고정되지 않음):

```json
{
  "text":"친구와 공놀이를 했다.\n즐거웠다.",
  "pages":[
    {"text":"친구와 공놀이를 했다.","source_ids":[1],"imageUrl":null},
    {"text":"즐거웠다.","source_ids":[3],"imageUrl":null}
  ],
  "sources":[
    {"id":1,"text":"친구와 공놀이를 했어."},
    {"id":3,"text":"즐거웠어."}
  ],
  "fallback":false,
  "requires_confirmation":true,
  "mock":false
}
```

- `sources[].id`는 요청 messages 배열의 0부터 시작하는 위치입니다. DB 메시지 ID가 아닙니다. BE는 필요하면 자체 메시지 ID와 대응시킵니다.
- `source_ids`는 해당 페이지의 글을 뒷받침하는 아이 발언 번호들입니다. AI 질문은 근거에 포함하지 않습니다.
- `fallback=true`일 때는 원문을 보존한 결과입니다. mock 모드이거나 일기 검토 실패일 수 있습니다.
- 이 API는 글만 생성합니다. 페이지 그림은 별도 /api/image 요청으로 생성합니다.
- `requires_confirmation=true`는 사용자 확인이 필요한 초안임을 뜻합니다. BE가 저장 시 확정 여부를 관리하세요.

## POST /api/image

FE에서 글을 확인하고 BE가 선택한 한 페이지의 글을 보냅니다.

```json
{"text":"친구와 공놀이를 했다.","confirmed":true}
```

응답 형식(데이터 URL 내용은 예시):

```json
{"imageUrl":"data:image/png;base64,...","requires_confirmation":true,"rejected":false}
```

완성된 그림 검토가 거절하면 HTTP 200이지만 다음 결과를 반환합니다.

```json
{"imageUrl":null,"requires_confirmation":true,"rejected":true}
```

이때 FE에 실패/제외 상태를 알리고 텍스트는 유지합니다. 이미지를 검사에서 거절해도 생성 비용은 발생할 수 있습니다. `confirmed`는 호출자의 확인 표시이며 AI 서비스가 실제 화면 클릭을 검증할 수는 없습니다. BE가 확인 절차를 보장해야 합니다. 그림을 생성한 뒤 글을 수정하면 기존 그림을 새 글의 그림으로 자동 재사용하지 마세요.

## 입력 제한·오류·시간

- messages: 최대 60개, 각 text: 1~2,000자, 대화 전체: 최대 20,000자
- role: child 또는 assistant만 허용
- image text: 1~1,500자
- 문서에 없는 필드는 거절합니다. 사용자 ID, 날짜, 인증 정보는 BE가 관리하고 AI 요청 본문에는 넣지 않습니다.
- 400: 이미지 글 확인 누락 (`{"detail":"..."}`)
- 422: 요청 자료형/필드/개수/개별 길이 오류 (`{"error":"..."}`)
- 503: 대화 총 길이 초과, 아이 발언 없는 일기 요청, 키 누락, 불완전 응답, mock 이미지 요청 (`{"error":"..."}`)
- 503: ProviderRouter가 변환한 공급자 인증·한도·연결·응답 형식 오류
- 502: 변환되지 않은 OpenAI SDK 오류 또는 Pydantic 모델 응답 형식 오류 (`{"error":"..."}`)

BE는 실패하면 입력을 보존하고 사용자가 명시적으로 재시도하도록 하세요. 이 API에는 중복 요청 제거 기능이 없으므로 자동 재시도는 비용을 늘릴 수 있습니다. SDK 통신 재시도는 꺼져 있습니다.

`/api/diary`는 생성·검토·최대 한 번의 재작성·재검토 전체에 **100초 요청 예산**을 적용합니다. 응답 구성에 1초를 남기고, 각 호출은 남은 예산과 60초 중 작은 timeout을 사용합니다. 생성에는 남은 시간의 절반까지만 배정해 검토 시간을 남깁니다. 최초 검토 거절 후 모델 예산이 10초 미만이면 재작성을 생략합니다. 예산 소진·재작성 생략·출처 검증 실패·최종 검토 거절은 기존 원문 `fallback=true`로 반환합니다. 실제 공급자 오류(개별 호출 timeout 포함)·형식 오류는 기존 HTTP 오류이며 자동 재시도하지 않습니다. 별도 HTTP 벽시계 제한도 적용하여 SDK가 늦어져도 예산 내 fallback 응답을 시작합니다. JSON 계약과 sources는 유지합니다. 자세한 경계는 [일기 시간 예산](DIARY_TIME_BUDGET.md)을 참고하세요.

BE의 135초 제한과 FE 제한은 변경하지 않습니다. 질문은 기존 생성+검토 각 60초, 그림은 묘사 60초+생성 180초+검토 60초 설정을 유지합니다. 이 개별 timeout 합계는 전체 요청의 엄격한 마감 시간이 아닙니다.

## v1.1 추가: POST /api/transcribe

Content-Type은 JSON이 아닌 multipart/form-data입니다. `file` 하나에 완성된 녹음을 전달합니다. 8 MiB 이하, 지원 확장자는 webm/mp4/m4a/wav/mp3/mpeg/mpga입니다. MIME과 확장자가 맞아야 하며 실제 음성 디코딩 가능 여부는 제공자가 판단합니다.

```json
{"text":"친구랑 공놀이를 했어.","requires_confirmation":true,"mock":false}
```

전사 초안이며, 해당 호출만으로 대화 이력이나 일기를 변경하지 않습니다. 무음·잡음 전사를 확정하기 전에 확인해야 합니다. 음성을 인식해 감정을 분석하는 기능은 없습니다.

추가 오류: 400 빈 파일, 413 크기 초과, 415 지원하지 않는 형식/불일치(`detail`). 503은 mock 모드·빈 전사·2,000자 초과 전사, 502는 제공자 호출 실패(`error`)입니다. 긴 전사 결과를 잘라 버리지 않습니다.

## v1.1 추가: POST /api/speech

요청 JSON:

```json
{"text":"그때 어떤 기분이 들었어?"}
```

성공 응답은 **JSON이 아니라 audio/mpeg MP3 바이너리**입니다. 문자열은 공백만인 입력을 제외하고 1~1,000자입니다. 실패 응답은 JSON error(422/502/503)입니다. BE는 HTTP 상태와 Content-Type을 확인한 뒤 오디오로 처리해야 합니다. mock에서는 503을 반환합니다.

## v1.1 추가: POST /api/voice-chat

요청은 기존 /api/chat과 같은 전체 messages JSON입니다. 첫 질문은 `{"messages":[]}`입니다. 이후에는 확인된 전사 텍스트를 child 메시지로 추가합니다. 이 API는 파일 업로드를 받지 않습니다.

```json
{
  "question":"어떤 놀이를 했어?",
  "finished":false,
  "mock":false,
  "fallback":false,
  "audio_base64":"SUQz...",
  "audio_mime_type":"audio/mpeg",
  "audio_error":null
}
```

MP3는 base64 문자열이며 data: 접두사나 영구 URL이 없습니다. 디코딩해 Blob/바이트로 처리합니다. 음성 합성에 실패하면 HTTP 200으로 question은 보존하고 audio_base64/audio_mime_type은 null, audio_error는 안내 문자열을 반환합니다. 이 경우 BE는 질문을 보관한 뒤 그 글로 /api/speech만 재시도할 수 있습니다. 질문 생성 자체가 실패하면 기존 502/503 오류를 반환합니다.

mock에서는 고정 질문과 null 오디오, mock 안내 audio_error를 반환합니다. API 키 없이 음성 파일이 만들어진 것처럼 표시하지 않습니다.

## v1.2 추가: 그림책·4컷 만화

`POST /api/visual-story`는 확인한 diary_text, confirmed, format(storybook/comic4/both), storybook_pages를 받아 그림책·4컷의 원문 기반 장면 구성을 반환한다. `POST /api/visual-story/image`는 그 응답의 diary_text, diary_hash, format, source_ids, confirmed로 한 장면의 그림을 생성한다.

이 API의 source_ids는 대화 메시지 위치가 아니라, 확인한 일기를 나눈 원문 조각 번호다. 이미지 생성은 장면별 별도 요청이며 모델 실패 시 HTTP 200/status=failed, 검토 거절 시 status=rejected를 반환한다. 같은 장면 반복은 reuse_scene_id로 재사용한다. FE는 그림책을 페이지로, 만화를 정확히 4칸의 2×2 격자로 표시한다. 상세 입력·응답·오류·변수는 [VISUAL_STORY.md](VISUAL_STORY.md)를 따른다.

이미지는 PNG 또는 JPEG data URL이다. 이미지 전체 디코딩 또는 검토 응답 완성에 실패하면 `/api/image`는 오류를, `/api/visual-story/image`는 status=failed를 반환한다. 완성된 검토의 accepted=false만 rejected로 분류한다.
