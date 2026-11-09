# BE 개발자 전달 문서 — 대화·일기·4컷 AI 연동

작성일: 2026-11-08

저장소: `WOOWANGTHON_TEAM_22_AI`

코드 기준: `main / 125684e` **이후의 로컬 수정 포함**. 아래 보완 사항은 아직 커밋·푸시하지 않았으므로 원격 HEAD만 받아서는 동일한 상태가 아니다.

## 1. 전달 요약

기존 `POST /api/chat`, `POST /api/diary`의 요청·응답 계약은 유지했다. 일기 출처와 최대 6페이지, null 이미지, 사용자 확인 플래그도 유지했다. BE의 기존 텍스트 연동 형식을 바꿀 필요는 없다.

이번에 동일 질문 반복 방지, 정정·종료 발언 처리 지침, 손상 이미지 차단, 이미지 검토 실패/거절 구분을 보완했다. 2026-11-09 일기 보완에서는 검토 거절 시 한 번 재작성·재검토를 추가했다. 모델·공급자 자동 변경이나 통신 오류 재시도는 없다. [일기 원인 분석 및 검증](DIARY_DRAFT_FIX.md)을 참고한다.

**텍스트 계약 검사와 실제 호출은 확인했지만, BE 서버·DB·Supabase를 연결한 종단간 검증은 하지 않았다.** 4컷은 실제 4장면을 요청했으며 생성 1컷·검토 거절 2컷·공급자 실패 1컷이었다. 네 컷이 모두 완성되는 품질이나 캐릭터 외형 일관성을 보장하는 상태는 아니다.

지시문에서 BE 대화·일기 및 원본 저장 구현 완료를 전달받았다. 이 문서는 그 상태를 전제로 AI와의 연결 방법을 설명하며, BE 구현 내용을 별도로 확인했다는 뜻은 아니다. 만화 생성·저장 API는 BE와 추가로 합의해야 한다. FE용 만화 주소는 아직 정하지 않았다.

## 2. 연결 주소와 실행

| 항목 | 값 |
|---|---|
| 같은 PC의 BE → AI | `http://127.0.0.1:8002` |
| API 확인 | `http://127.0.0.1:8002/docs` |
| 실제 스키마 | `http://127.0.0.1:8002/openapi.json` |
| 상태 확인 | `GET /api/status` |
| 로컬 개발 화면 | `/dev/voice` — 제품 FE 연결용 주소가 아님 |

다른 PC나 Docker 컨테이너의 localhost는 AI 서버를 가리키지 않는다. 해당 환경의 주소·바인딩·접근 경로는 BE 담당과 별도로 정한다. 기본 실행은 127.0.0.1 바인딩이다. 제품 흐름은 **FE → BE → AI**다. AI 서버에는 사용자 인증·DB 저장·파일 영구 저장이 없으며 BE가 담당한다.

AI 저장소에서 실행:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

이미지 파일 전체 검사에 필요한 Pillow가 런타임 의존성에 추가됐다. 기존 환경도 requirements.txt를 다시 설치해야 한다. `.env`는 덮어쓰지 않는다. Groq/Cloudflare 키는 AI 서버에만 보관하고 요청 JSON이나 FE에 넣지 않는다.

`/api/status`의 `configured=true`는 텍스트 키 존재 여부이며 실제 키 유효성·이미지 생성 성공을 뜻하지 않는다. `mode=openai`는 기존 명칭으로 남아 있는 **실제 호출 모드**이며 공급자가 반드시 OpenAI라는 뜻이 아니다. 빈 messages의 첫 질문도 모델을 호출하지 않으므로 실연결 검증에 충분하지 않다.

## 3. 대화·일기 API — 기존 계약 유지

모든 요청은 JSON이다. 모델에 없는 추가 필드는 거절된다. user_id, 날짜, 세션 ID, 메시지 DB ID는 BE에서 보관하고 AI 요청에 넣지 않는다. AI는 대화 상태를 저장하지 않으므로 매번 전체 대화를 원래 순서대로 보낸다.

### POST /api/chat

실제 검증에 사용한 요청:

```json
{
  "messages": [
    {
      "role": "assistant",
      "text": "오늘 무슨 일이 있었어?"
    },
    {
      "role": "child",
      "text": "친구랑 공원에서 공놀이 했어."
    }
  ]
}
```

해당 실제 응답:

```json
{
  "question": "공놀이를 할 때 어떤 공을 썼어?",
  "finished": false,
  "mock": false,
  "fallback": false
}
```

| 응답 필드 | 자료형 | BE 처리 |
|---|---|---|
| question | string | 질문 또는 종료 안내를 표시·저장 |
| finished | boolean | true면 후속 입력을 마무리하도록 안내; 일기 저장 완료라는 뜻은 아님 |
| mock | boolean | true면 실제 모델 품질 검증 대상에서 제외 |
| fallback | boolean | true면 생성 질문 대신 대체 안내; 공급자 호출 자체의 성공을 보장하지 않음 |

`finished=true`만으로 일기가 생성·저장되지는 않는다. 이후 `/api/diary`를 별도로 요청한다. 명확한 종료 문장은 로컬 규칙으로 처리하므로 `mock=false`라도 모델 호출이 생략될 수 있다.

### POST /api/diary

요청 형식은 `/api/chat`과 같다. 다음은 **이전 단순 일기 실검증 표본**이며 최신 복잡한 정정 시나리오와 별개다.

```json
{
  "messages": [
    {
      "role": "assistant",
      "text": "오늘 무슨 일이 있었어?"
    },
    {
      "role": "child",
      "text": "집에서 파란 블록을 쌓았어."
    },
    {
      "role": "assistant",
      "text": "어떤 기분이 들었어?"
    },
    {
      "role": "child",
      "text": "재미있었어."
    }
  ]
}
```

실제 응답:

```json
{
  "text": "집에서 파란 블록을 쌓았다. 재미있었다.",
  "pages": [
    {
      "text": "집에서 파란 블록을 쌓았다.",
      "source_ids": [
        1
      ],
      "imageUrl": null
    },
    {
      "text": "재미있었다.",
      "source_ids": [
        3
      ],
      "imageUrl": null
    }
  ],
  "sources": [
    {
      "id": 1,
      "text": "집에서 파란 블록을 쌓았어."
    },
    {
      "id": 3,
      "text": "재미있었어."
    }
  ],
  "fallback": false,
  "requires_confirmation": true,
  "mock": false
}
```

| 응답 필드 | 자료형 | 유지되는 의미 |
|---|---|---|
| text | string | 일기 초안 또는 fallback 원문 |
| pages | array | 최대 6개; 각 항목은 text:string, source_ids:integer[], imageUrl:null |
| sources | array | 모든 child 발언의 id:integer와 원문 text:string |
| fallback | boolean | true면 원문 보존 대체 결과 |
| requires_confirmation | boolean | 항상 true; 사용자가 확인할 초안 |
| mock | boolean | mock 모드 구분 |

**sources.id는 요청 messages 전체 배열의 0-based 위치**다. 위 예시의 child는 1번·3번이며 child끼리 다시 0번·1번으로 번호를 매기면 안 된다. sources의 원문과 순서를 유지하고 pages[].source_ids를 해당 목록에 대응시킨다. 메시지 DB ID와의 매핑은 BE가 관리한다.

본문은 생성 일기에서는 문장 사이 공백, fallback에서는 발언 사이 줄바꿈을 사용한다. 페이지 내부 줄바꿈과 본문 구분자가 다를 수 있으므로 단순 문자열 연결 비교 대신 기존 BE의 정규화 규칙과 출처 검사를 적용한다.

fallback=true는 확정본이 아니다. 정정 전 발언과 나중 정정, 종료 요청까지 원문으로 함께 남을 수 있다. 원문을 보존하고 사용자가 수정·확인한 최종본을 별도로 관리한다. 공급자 오류는 정상 일기 JSON 대신 HTTP 오류가 반환된다.

## 4. 4컷 API — BE 생성·저장 흐름 추가 필요

권장 순서는 다음과 같다. 이는 AI 호출 순서이며 새로운 BE URL을 확정한 것이 아니다.

1. BE가 사용자가 확인한 일기 최종본과 버전을 확보한다.
2. `/api/visual-story`로 장면을 구성한다.
3. 고유 장면마다 `/api/visual-story/image`를 호출한다. 반복 장면은 재사용한다.
4. 컷별 상태를 보관하고 성공 이미지를 파일 저장소에 저장한다.
5. 사용자가 확인한 결과를 FE의 2×2 배치에 연결한다. 실패한 컷만 별도 재시도한다.

### POST /api/visual-story

실제 요청:

```json
{
  "diary_text": "빨간 공을 굴렸다. 파란 블록을 쌓았다. 종이에 동그라미를 그렸다. 책을 펼쳤다. 책을 덮었다.",
  "format": "comic4",
  "confirmed": true
}
```

전체 실제 응답은 [plan.response.json](be_examples/plan.response.json)에 있다. 최상위 필드는 diary_text, diary_hash, sources, storybook, comic4, requires_confirmation, mock이다.

- `comic4.layout=grid_2x2`, scenes는 정확히 4개이며 order는 1~4다.
- 각 scene은 scene_id, order, caption, source_ids, imageUrl, repeated, reuse_scene_id를 가진다. caption은 해당 원문 조각을 순서대로 연결한 글이며 초기 imageUrl은 null이다.
- `format=comic4`면 storybook=null이다. format은 storybook/comic4/both를 지원하며 기본값은 both다. storybook_pages는 1~6, 기본 4이며 comic4 컷 수에는 영향을 주지 않는다.
- planning_mode는 model/deterministic/fallback/mock이다. deterministic은 조각 수상 묶음이 자명하여 모델 호출을 생략한 경우다. fallback은 구성 실패 후 원문 순서 분배다.
- 이 API의 sources.id는 **확인한 일기를 분할한 조각 번호**다. `/api/diary`의 messages 인덱스와 다르다.

### POST /api/visual-story/image

아래는 실제 성공한 3번 컷의 요청이다. 다른 일기에는 이 해시를 재사용하지 말고 새 plan의 값을 사용한다.

```json
{
  "diary_text": "빨간 공을 굴렸다. 파란 블록을 쌓았다. 종이에 동그라미를 그렸다. 책을 펼쳤다. 책을 덮었다.",
  "diary_hash": "8884860bb3c860bb186995f5919514141f10b6cd7b4e72027573b79bf56079b9",
  "source_ids": [
    2,
    3
  ],
  "format": "comic4",
  "confirmed": true
}
```

응답은 다음 필드를 갖는다. base64는 문서 길이 때문에 아래에서만 축약했다. 디코딩 가능한 전체 실제 응답은 [comic4-3.response.json](be_examples/comic4-3.response.json)에 있다.

```json
{
  "diary_hash": "8884860bb3c860bb186995f5919514141f10b6cd7b4e72027573b79bf56079b9",
  "scene_key": "461309fb715e83e0567dc4085d39d35a37d43003c52f3e0b218f005e0fa8f317",
  "caption": "종이에 동그라미를 그렸다.\n책을 펼쳤다.",
  "source_ids": [
    2,
    3
  ],
  "format": "comic4",
  "imageUrl": "data:image/jpeg;base64,<문서에서만 축약; 전체 JSON 파일 참조>",
  "status": "generated",
  "error": null,
  "requires_confirmation": true,
  "mock": false
}
```

| status | imageUrl | 의미와 BE 처리 |
|---|---|---|
| generated | PNG/JPEG data URL | 생성·자동 검토 통과. 파일 저장 후 사용자 확인 |
| rejected | null | 완성된 검토가 거절. 텍스트·다른 성공 컷 유지 |
| failed | null | 생성·디코딩·검토 처리 실패. error 안내, 해당 컷만 재시도 |
| mock | null | 실제 그림 없음. 저장 완료로 처리하지 않음 |

**HTTP 200만으로 성공 처리하지 않는다.** 검토 응답이 비거나 중간에 끊긴 경우도 failed다. error는 사람에게 보여줄 안내 문자열이며 안정적인 기계용 오류 코드는 아직 없다. 메시지 문구를 파싱해 자동 재시도를 결정하지 않는다.

### 재사용·부분 실패·버전

원문이 짧으면 4컷을 채우기 위해 마지막 장면이 반복된다. `repeated=true`인 컷의 `reuse_scene_id`가 가리키는 원본 컷 이미지를 참조한다. 반복은 새 사건이나 시간 경과를 뜻하지 않는다. [short_plan.response.json](be_examples/short_plan.response.json)에 1문장 → 4컷 실제 결과가 있다.

같은 diary_hash·format·source_ids의 scene_key는 같다. 다만 해시는 사용자 소유권 검증이나 AI 서버의 중복 요청 방지 기능이 아니다. BE가 사용자/일기 버전별로 작업을 구분해야 한다. 글 수정 후 늦게 도착한 이전 해시의 결과를 새 일기에 붙이지 않는다. 실패 또는 거절이 나와도 다른 성공 컷의 저장 기록을 지우지 않는다.

### 이미지 저장

imageUrl은 영구 URL이 아니다. BE가 `data:image/jpeg;base64,` 또는 `data:image/png;base64,` 접두사와 파일 형식을 확인해 디코딩·저장하고 조회 URL을 만들어야 한다. 실제 성공 표본은 둘 다 JPEG 1024×1024다. 모든 공급자 결과의 크기가 항상 같다고 가정하지 않는다.

아이의 원본 그림, AI 만화 이미지, 일기 최종본은 별도 자산/버전으로 관리한다. 저장 구조·작업 상태명은 BE 설계 사항이며 AI 응답에 DB 필드를 추가하지 않는다.

## 5. 기존 개별 이미지와 음성

| 경로 | 입력 | 결과·주의 |
|---|---|---|
| POST /api/image | text, confirmed:true | imageUrl, requires_confirmation, rejected. 만화 API의 status 필드는 없음 |
| POST /api/transcribe | multipart file | text, requires_confirmation, mock. 사용자가 확인한 뒤 child로 추가 |
| POST /api/speech | text | 성공은 JSON이 아닌 audio/mpeg MP3 |
| POST /api/voice-chat | messages | chat 4필드 + audio_base64, audio_mime_type, audio_error |

기존 이미지의 실제 요청·전체 응답은 [legacy_image.request.json](be_examples/legacy_image.request.json), [legacy_image.response.json](be_examples/legacy_image.response.json)에 있다. mock의 `/api/image`는 503이며 만화 API처럼 status=mock을 반환하지 않는다.

현재 서버 TTS는 disabled다. `/api/voice-chat`의 음성만 실패하면 질문은 유지되고 오디오는 null, audio_error에 안내가 담긴다. `/api/speech`는 오류를 반환한다. 음성 상세 계약은 [API_CONTRACT.md](API_CONTRACT.md)를 따른다. 이번 실검증의 주 대상은 텍스트·만화이며 실제 마이크/TTS 품질을 재검증한 것은 아니다.

## 6. 입력 제한과 HTTP 오류

| 항목 | 현재 제한 |
|---|---|
| messages | 최대 60개; role은 assistant/child |
| 메시지 text | 1~2,000자; 대화 전체 20,000자 이하 |
| 만화 diary_text | 1~6,000자, 공백만인 글 불가, 원문 조각 최대 80개 |
| 만화 image source_ids | 1~80개, 유효한 연속 번호를 오름차순으로 전달 |
| 기존 image text | 1~1,500자 |
| speech text | 1~1,000자, 공백만인 글 불가 |
| 음성 파일 | 최대 8 MiB; webm/mp4/m4a/wav/mp3/mpeg/mpga, MIME 대응 확인 |

| HTTP | 대표 상황 | 응답 모양 |
|---|---|---|
| 400 | confirmed 누락/false, 빈 음성 파일 | `{"detail":"..."}` |
| 409 | 이미지 요청 diary_hash 불일치 | `{"detail":"..."}` |
| 413 / 415 | 음성 크기 / 형식 오류 | `{"detail":"..."}` |
| 422 | 자료형·추가 필드·개별 길이 오류 | 보통 `{"error":"..."}`; 만화의 공백/조각 수/출처 검사 일부는 detail |
| 503 | 대화 총길이 초과, child 없는 일기, 키 누락, Router가 변환한 공급자 오류 | `{"error":"..."}` |
| 502 | 변환되지 않은 SDK 오류·모델 자료형 오류 | `{"error":"..."}` |

만화 이미지의 공급자 실패는 위 HTTP 오류 대신 **HTTP 200/status=failed**로 처리된다. BE는 먼저 HTTP를 확인하고, 성공 코드면 각 API의 상태 필드를 확인한다. 알 수 없는 오류도 기존 입력·정상 결과를 보존한다.

## 7. 시간·재시도·공급자

현재 설정은 텍스트 Groq `openai/gpt-oss-20b`, 이미지 Cloudflare `@cf/black-forest-labs/flux-1-schnell`(4 steps), 이미지 검토 Groq `qwen/qwen3.8-27b`다.

| 요청 | 기본 외부 호출 수 | 개별 SDK timeout |
|---|---|---|
| 일반 질문 | 텍스트 생성+검토, 보통 2회 | 각 60초 |
| 일기 | 생성+검토 2회; 시간 여유가 있는 검토 거절 시 한 번 보정해 최대 4회 | 전체 요청 100초 예산, 각 호출은 남은 예산 이내(최대 60초) |
| 명확한 종료·첫 고정 질문 | 0회 | 로컬 처리 |
| 모델 장면 구성 | 보통 1회; deterministic이면 0회 | 60초 |
| Cloudflare 이미지 한 장 | 텍스트 묘사+이미지 생성+비전 검토, 보통 3회 | 60초+180초+60초 |

SDK의 개별 timeout은 요청 전체의 엄격한 총 마감 시간이 아니다. 일기는 별도 HTTP 벽시계 제한과 100초 전체 예산을 적용한다. 응답용 1초를 남기고 최초 검토 거절 후 모델 예산이 10초 미만이면 보정을 생략해 원문 fallback으로 반환한다. 실제 공급자 오류·개별 호출 timeout은 기존 오류 응답이다. [세부 정책](DIARY_TIME_BUDGET.md)을 참고한다. BE 135초 제한과 FE 제한은 늘리지 않는다. 검토 거절 시 최대 4회 순차 호출로 비용은 늘 수 있다. BE 텍스트 timeout을 이미지에 그대로 적용하지 않는다. **이미지는 BE 비동기 작업과 컷별 상태 저장을 권장**하며, 이미지 요청/프록시 timeout·동시성은 BE와 합의한다. AI에 서버 배치·작업 ID·통신 오류 자동 재시도·영구 캐시가 구현된 것은 아니다. HTTP 응답 제한이 끝나도 이미 진행 중인 외부 생성의 취소는 보장하지 않는다. 늦은 결과는 사용하지 않고 추가 모델 호출도 하지 않는다.

검토 거절도 생성 비용이 들 수 있다. 실청구액과 토큰 사용량은 측정하지 않았다. 참고용 기존 가격 확인값(2026-11-08)은 텍스트 입력 $0.075/백만 토큰·출력 $0.30/백만 토큰, FLUX 1024×1024·4 steps 가정 시 생성만 약 $0.0006336/장이다. 텍스트 묘사·비전 검토·재시도 비용은 별도이며 무료 할당량에 따라 실청구액은 다르다. [Groq 가격](https://console.groq.com/docs/model/openai/gpt-oss-20b), [Cloudflare 가격](https://developers.cloudflare.com/workers-ai/platform/pricing/)를 과금 계획 전에 확인한다.

## 8. 실제 검증 결과와 한계

Python 114개·JavaScript 21개 자동 테스트가 통과했다. 가짜 공급자 테스트와 실제 호출 기록은 구분했다. 실제 BE 검증기 대신 제공된 BE 계약의 필드·페이지·원문 출처 조건을 검사했다.

| 검증 항목 | 관측 결과 |
|---|---|
| 후속 질문/짧은 답/정정/거절 | 실제 HTTP 200, fallback=false, 1.558~2.479초 |
| 종료 요청 | finished=true, 0.006초; 모델 호출 없는 로컬 처리 |
| 복잡한 정정 일기 | 2.204초, fallback=true, 원문 보존·구조 검사 통과 |
| 단순 일기(이전 실행) | 1.717초, fallback=false; 별도 표본 |
| 실제 4컷 구성 | 0.968초, planning_mode=model, 정확히 4컷 |
| 짧은 원문 | 0.007초, deterministic, 반복 컷 재사용 정보 포함 |
| 컷1 / 컷2 | rejected / rejected, 3.793 / 4.621초 |
| 컷3 / 컷4 | generated / failed, 4.005 / 2.366초 |
| 기존 /api/image | 3.393초, rejected=false, JPEG 1024×1024 |

4컷 요청 평균 3.696초, 최대 4.621초다. 해당 4개 표본의 이미지 미반환율은 75%이며 일반적인 서비스 실패율이나 SLA로 사용할 수 없다. 성공 3번 컷은 94,941바이트, 기존 개별 이미지는 77,067바이트다. 생성 이미지 전체 디코딩을 확인했지만 3번 컷은 선이 끊겨 행동 가독성이 낮았다. 자동 검토 통과가 완성된 제품 품질을 보장하지 않는다.

## 9. BE와 확정할 사항

- **만화 입력 길이:** BE 일기 최대 20,000자와 AI 만화 6,000자 차이가 있다. 1차 연결에서는 초과 원문을 자르지 않고 만화 생성을 보류하는 방안을 제안한다. 사용자 승인 범위 선택 또는 AI 한도 확대는 별도 합의가 필요하다.
- **만화 생성·저장 API:** BE 요청/조회 방식, 작업 ID, 컷별 상태, 재시도·중복 요청 정책을 정한다. FE 주소를 AI 담당이 임의로 정하지 않는다.
- **버전·자산:** 일기 초안/확정본, 원본 아이 그림/AI 이미지, 사용자 소유권 및 수정 뒤 오래된 결과 처리를 맞춘다.
- **실행 환경:** 타 PC/컨테이너 주소, 내부 접근 경로, 이미지 timeout·동시 요청 수를 맞춘다.
- **품질 승인:** 높은 이미지 거절률과 캐릭터 일관성은 미해결이다. 기능이 호출된다는 사실과 사용자에게 제공할 품질 승인을 구분한다.

## 10. BE 연결 확인 순서

저장소 루트에서 다음 요청을 실행할 수 있다. 실제 모드는 외부 호출 비용이 발생한다. 동적 출력은 매번 달라질 수 있다.

```sh
curl -s http://127.0.0.1:8002/api/status
curl -s http://127.0.0.1:8002/api/chat \
  -H 'Content-Type: application/json' \
  --data-binary @docs/be_examples/followup.request.json
curl -s http://127.0.0.1:8002/api/diary \
  -H 'Content-Type: application/json' \
  --data-binary @docs/be_examples/simple_diary_previous_run.request.json
curl -s http://127.0.0.1:8002/api/visual-story \
  -H 'Content-Type: application/json' \
  --data-binary @docs/be_examples/plan.request.json
```

BE 통합 시에는 마지막 명령의 **새 응답**에서 diary_text/diary_hash/각 source_ids를 꺼내 이미지 요청을 만든다. 고정 샘플 해시를 다른 일기에 적용하지 않는다.

- [ ] 기존 대화/일기 BE 검증기가 실제 응답을 통과한다.
- [ ] child 출처 위치와 원문, 페이지 제한이 저장 후에도 유지된다.
- [ ] fallback과 사용자 확인 상태를 확정 저장 상태와 구분한다.
- [ ] 만화 4개 슬롯·반복 컷·부분 실패·개별 재시도가 동작한다.
- [ ] 이미지 MIME/파일 저장·원본 그림 분리·일기 버전 비교가 동작한다.
- [ ] 6,000자 초과·해시 불일치·공급자 실패·timeout 시 입력과 성공 컷이 유지된다.

샘플 전체 목록은 [be_examples/manifest.json](be_examples/manifest.json)에 있다. 파일명마다 요청과 응답이 한 쌍이며 HTTP 코드·소요 시간·검증 실행 구분을 기록했다. 성공 이미지 응답의 base64는 축약하지 않아 디코딩 테스트에 사용할 수 있다. 샘플은 모두 가상 대화이며 실제 API 키는 포함하지 않는다.
