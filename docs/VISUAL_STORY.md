# 확인한 일기 → 그림책·4컷 만화 (AI v1.2)

## 이번에 추가한 기능

대화로 작성한 일기의 내용을 사람이 확인한 후, 그림책과 4컷 만화의 장면 글을 구성하고 장면별 그림을 생성한다. 기존 텍스트·음성 대화, 일기 API는 유지한다.

- 그림책: 원문 조각 수에 따라 1~6페이지. 기본 요청은 최대 4페이지이다.
- 4컷 만화: 정확히 4컷, 왼쪽 위→오른쪽 위→왼쪽 아래→오른쪽 아래 순서이다.
- 입력이 짧으면 같은 장면을 반복한다. 새로운 사건, 결말, 대사를 지어내지 않는다.
- 글은 확인된 일기의 문장들을 그대로 연결한다. 모델에게 새 캡션을 쓰게 하지 않고 원문 번호의 묶음만 받는다.
- 그림책은 수채화 삽화, 만화는 단일 컷의 또렷한 선·평면 색을 사용한다.
- 글은 이미지 밖에서 FE가 표시한다. 이미지 안에는 한글 캡션이나 말풍선을 생성하지 않는다.
- 표준 Cloudflare 4컷은 생성·디코딩·OCR·시각 보조 검사를 거친 뒤 사용자 확인을 요구한다. 그림책과 다른 공급자의 경로는 유지한다.

**이 파일은 AI 기능 추가 안내다.** FE 화면·완성된 PDF·4컷 합본 PNG를 만드는 코드는 포함하지 않는다. AI는 장면별 글·그림과 layout을 반환하고 FE가 페이지 또는 2×2 격자로 표시한다. BE는 결과·이미지를 저장한다. 실제 호출 결과와 남은 품질 문제는 [통합 검증 기록](INTEGRATION_VERIFICATION.md) 및 [요구사항 재점검](REQUIREMENTS_AUDIT.md)에 구분해 기록한다.

## 실행과 의존성

현재 checkout 전체를 기준으로 `python -m pip install -r requirements.txt` 후 `python prepare_ocr.py`로 로컬 OCR 모델을 준비하고 실행한다. 최초 준비에는 모델 다운로드가 필요하므로 배포 이미지 빌드 단계에서 수행한다. 이미지 데이터 전체 디코딩 검사를 위해 Pillow가 필요하다. `.env` 설정은 [공급자 안내](MULTI_PROVIDER_SETUP.md)를 따른다. 서버가 실행 중이면 재시작한다.

```sh
python server.py
```

개발 API 문서는 http://127.0.0.1:8002/docs 이다.

## 입력은 어디서 가져오나?

1. 기존 `/api/diary`에 대화를 보내 일기 text를 받는다.
2. 아이/보호자가 글을 확인·수정한다.
3. BE가 확인한 최종 글을 새 API의 diary_text로 전달한다.

새 API는 **확인된 diary_text를 사실의 기준으로 사용**한다. 초기 대화와의 재대조는 이 API에서 하지 않는다. 이미 일기에 잘못된 정보가 있으면 그대로 그림의 기준이 되므로 기존 원문 비교·확인 절차를 유지한다. `confirmed`는 호출자가 보낸 표시이지 사용자 클릭을 AI가 검증한 결과가 아니다.

## 1단계: 그림책·4컷 구성 요청

`POST /api/visual-story`, Content-Type application/json

```json
{
  "diary_text":"오늘 공원에 갔다. 친구와 공놀이를 했다. 즐거웠다. 집에서 저녁을 먹었다.",
  "confirmed":true,
  "format":"both",
  "storybook_pages":4
}
```

format은 storybook / comic4 / both 중 하나이다. both면 둘 다 반환한다. storybook_pages는 1~6이고 comic4의 컷 수에는 영향을 주지 않는다.

응답 주요 필드:

| 필드 | 설명 |
| --- | --- |
| diary_text | 앞뒤 공백을 정리한 입력 일기 |
| diary_hash | 위 일기의 SHA-256 값. 다음 이미지 요청에 그대로 사용 |
| sources | 문장 끝 공백 또는 줄바꿈으로 나눈 원문 조각 목록 |
| storybook | 그림책 구성. 요청하지 않으면 null |
| comic4 | 정확히 4컷 구성. 요청하지 않으면 null |
| requires_confirmation | 장면 구성을 확인해야 한다는 표시 |
| mock | 실제 생성 모드 여부 |

각 구성은 format, layout, planning_mode, scenes, notices를 가진다.

- layout: 그림책은 pages, 만화는 grid_2x2.
- planning_mode: model(모델이 묶음 결정), deterministic(묶음이 자명해 모델 호출 생략), fallback(모델 오류·검사 실패로 순서대로 분배), mock(키 없이 시험).
- scenes: 순서대로 표시할 장면. 각 장면은 scene_id, order(1부터), caption, source_ids, imageUrl, repeated, reuse_scene_id를 가진다.
- 최초 imageUrl은 null이다. 이 호출은 그림을 생성하지 않는다.
- notices에는 원문 반복이나 원문 순서 대체 등의 안내가 들어간다.

짧은 일기 예: `사과를 먹었다.`라면 그림책은 1페이지, 만화는 같은 장면 4컷이다. 2~4번째 컷은 repeated=true이고 reuse_scene_id가 comic4-1이다. FE는 반복 컷임을 표시하고 BE는 첫 컷의 그림을 재사용해 불필요한 이미지 요청을 피한다. 네 번 사과를 먹은 것으로 설명하지 않는다.

**새 source_ids는 이 API의 sources 내 번호다.** 기존 /api/diary의 대화 메시지 위치와 다르다. 서로 섞지 않는다. 모델이 없는 번호, 누락, 중복, 순서 변경을 반환하면 모두 원문 순서 분배로 대체한다. 반복 컷은 이 검사를 마친 뒤 서버가 명시적으로 추가한다.

## 2단계: 장면별 그림 생성

`POST /api/visual-story/image`, Content-Type application/json

앞 단계 응답의 diary_text, diary_hash와 해당 장면의 source_ids를 그대로 보낸다. 아래 diary_hash는 실제 응답의 64자리 값으로 바꿔야 한다.

```json
{
  "diary_text":"오늘 공원에 갔다. 친구와 공놀이를 했다. 즐거웠다. 집에서 저녁을 먹었다.",
  "diary_hash":"앞_단계의_실제_diary_hash로_교체",
  "format":"comic4",
  "source_ids":[0],
  "confirmed":true
}
```

format은 storybook 또는 comic4이다. both는 이미지 요청에서 사용하지 않는다. 사용자가 임의의 이미지 프롬프트나 caption을 보내지 않고 서버가 원문 번호로 글을 재구성한다.

성공 시 다음 필드를 반환한다.

| 필드 | 설명 |
| --- | --- |
| diary_hash | 요청 일기의 버전 확인용 값 |
| scene_key | 일기+형식+원문 번호 조합의 해시 |
| caption / source_ids / format | 이 그림의 기준 글과 근거 |
| imageUrl | 생성·검토를 통과한 PNG/JPEG 데이터 URL 또는 null |
| status | generated / rejected / failed / mock |
| error | 실패 안내 또는 null |
| requires_confirmation | 생성 그림을 사람이 확인해야 한다는 표시 |
| mock | 체험 모드 여부 |

HTTP 200이라도 status가 generated인지 확인한다.

- generated: imageUrl을 표시하고 사용/제외를 확인한다.
- rejected: 완성된 검토가 accepted=false로 거절한 그림은 반환하지 않는다. 글은 유지한다.
- failed: 모델 요청, 이미지 디코딩 또는 검토 처리 실패(빈 응답·잘린 응답 포함). error를 안내하고 해당 장면만 재시도한다.
- mock: 실제 그림 없이 구조만 반환한다. imageUrl은 null이다.

같은 원문이라도 그림책과 만화의 scene_key는 다르다. 같은 형식·같은 원문의 반복 컷은 같은 scene_key이므로 재사용할 수 있다. **해시는 인증·서명이 아니며 AI에 중복 호출 제거 저장소가 있는 것도 아니다.** BE가 세션/사용자 권한, 생성 버전, 장면별 중복 요청을 관리한다.

## FE/BE 연결 순서

```text
확인된 일기
 → BE: /api/visual-story (both)
 → FE: 그림책 / 4컷 만화 선택, 페이지 글 확인
 → BE: 고유 장면별 /api/visual-story/image
 → FE: 장면별 준비 중 / 그림 / 실패 상태 표시
 → 사용자 그림 확인
 → BE: 최종 글·그림·형식 저장
```

FE는 그림책 scenes를 페이지로, comic4 scenes를 2×2 격자로 표시한다. 캡션은 반환 순서대로 이미지 밑에 그대로 표시한다. 반복 컷의 그림은 reuse_scene_id로 참조한다. 별도 말풍선·반전·결말을 임의로 생성하지 않는다.

BE는 API 결과의 PNG/JPEG 데이터 URL을 바이너리로 디코딩해 기존 파일 저장소에 저장하고 FE용 URL로 바꿀 수 있다. 일기 글이 수정되면 구성을 다시 생성하고 이전 그림은 새 일기에 자동 연결하지 않는다. 응답이 늦게 도착했을 때 diary_hash와 페이지 버전을 비교해 오래된 결과를 폐기한다.

## 제한·오류

- 입력 일기: 공백을 제외하고 비어 있지 않아야 하며 필드 길이는 최대 6,000자.
- 원문 조각: 최대 80개. 긴 일기를 임의로 잘라 버리지 않고 오류를 반환한다.
- 이미지 source_ids: 1~80개, 유효한 연속 번호를 오름차순으로 전달.
- 400: confirmed=false 또는 확인 표시 누락.
- 409: diary_text가 diary_hash와 일치하지 않음. 구성을 다시 요청.
- 422: 형식·길이·근거 번호 오류.
- 모델 구성 오류는 planning_mode=fallback으로, 이미지 처리 오류는 HTTP 200/status=failed로 반환한다. BE는 상태 필드를 반드시 확인한다.

Cloudflare 그림책은 기존 장면별 경로를 유지한다. 표준 4컷 만화는 Cloudflare 장면 모델
1회로 원문 근거·사물·구체적 행동을 작성하고 검사한 뒤 FLUX.1 schnell로 각 장면을
각각 생성한다(4회, steps=8). 합본 실험에서는 여러 사건이 섞여 현재는 한 이미지에
한 사건만 전달한다. 네 이미지의 2×2 배치는 FE가 담당하며 API 필드는 유지한다.

장면의 source_quote/action_quote가 해당 컷 원문에 실제로 있고, 사물 근거가 현재 또는
이전 컷에 있는지 검사한다. 번호가 잘못되거나 영어 행동 문장이 불완전하면 이미지 생성
전에 실패한다. 글자수 한도 때문에 원문이나 시각 명세를 몰래 자르지 않는다.
이 검사는 인용의 존재·형식 검사이며 번역/의미의 완전한 정확성을 보증하지 않는다.

각 그림은 Cloudflare 시각 모델로 핵심 사물·개수·행동·색상·추가 요소·글자·단일 장면·캐릭터를 검사한다. 개수는 모델의 단순 통과 판정과 별도로 코드에서 대조한다. 불완전 응답이나 검사 장애는 실패로 처리하고 검사하지 않은 그림을 통과시키지 않는다. 앞 장면 그림은 캐릭터 참조로만 사용한다.

로컬 RapidOCR에서 글자가 탐지되면 작은 영역만 국소 복원하고 재검사한다. 8%보다 넓은
영역은 지우지 않는다. 글자가 남거나 시각 검사에서 불일치가 있으면 네 장면 전체에서 최대 1회만 재생성한다.
최대 이미지 생성은 5회이며, 모든 검사를 통과한 네 이미지가 모였을 때만 반환한다.
중간 장면의 공급자 호출이 실패하면 status=failed, 문자 또는 시각 검사에 계속 걸리면
status=rejected로 반환한다. `generated`는 표준 만화에서 보조 시각 검사를 통과한 상태이지만, 일기와 완전히 일치한다는 보증은 아니다.

원문 해시와 네 이미지 결과만 프로세스 메모리에 5분, 최대 4개 작업/32MB까지 보관한다.
원문·장면 명세·OCR 인식 문자열은 기본 코드에서 디스크나 로그에 저장하지 않는다.
실패 안내는 15초간 재사용하여 나머지 컷 요청마다 생성 호출을 반복하지 않는다.
동시 요청은 잠금으로 중복 생성을 막는다. 다중 워커·서버 간에는 캐시가 공유되지 않으므로
BE는 같은 작업을 한 워커로 순차 요청하거나 결과를 직접 저장해야 한다.

HTTP 400·401·403·429 및 안전 필터 거절은 자동 재시도하지 않는다. 502·503·504만
남은 시간 안에서 최대 1회 재시도한다. 원문·키·공급자의 원본 오류는 출력하지 않는다.
장면 명세는 최대 55초, 전체 장면 생성은 기존 180초 잔여 시간을 공유한다.
HTTPX 단계별 제한이므로 엄격한 외부 작업 취소와 동일하지는 않다.

장면별 다시 만들기는 캐시 유효 기간 안에서는 같은 네 이미지 결과를 반환한다.
5분 후 재요청하거나 서버를 재시작하면 새로 생성한다. 강제 재생성 플래그나 작업 ID는
추가하지 않았다. 표준 그룹 밖의 유효한 source_ids는 기존 단일 컷 경로를 유지한다.

## 변수·함수 설명

| 이름 | 역할 |
| --- | --- |
| diary_text / confirmed | 확인된 일기와 호출자의 확인 표시 |
| format / storybook_pages | 결과 형식과 그림책 최대 페이지 수 |
| sources / source_ids | 이 일기의 원문 조각과 번호 |
| target / groups | 실제 장면 수와 장면별 원문 번호 묶음 |
| candidate / proposed / flattened | 모델 구성안, 번호 묶음, 누락·순서 검사 배열 |
| caption | 원문을 그대로 연결한 글 |
| planning_mode / notices | 장면 구성 방식과 안내 |
| repeated / reuse_scene_id | 같은 사건을 늘리지 않고 반복하는 컷의 표시 |
| diary_hash / scene_key | 일기 버전과 형식·근거 조합 비교 값 |
| IMAGE_RULES / STYLES | 그림 생성의 원문 보존 규칙과 표현 스타일 |
| REVIEW_PROMPT | 이미지에 없는 사건·감정 등이 추가됐는지 확인하는 지침 |
| source_data() / even_groups() | 원문 분리 / 실패 시 순서 유지 분배 |
| VisualStoryService.plan() | 그림책·4컷 구성 생성 |
| VisualStoryService.render() | 한 장면의 글 검증 및 이미지 결과 반환 |
| _generate_image() | 실제 이미지 모델 호출 후 시각 검토 |

## 검증 및 남은 한계

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

현재 테스트 개수와 실제/모의 결과는 [요구사항 재점검](REQUIREMENTS_AUDIT.md)을 참고한다. 모의 검사는 실제 모델 품질의 근거가 아니다.

글의 원문 보존은 코드에서 검사한다. 같은 캐릭터 지시를 공유하지만 각 장면을 독립적으로
생성하므로 외모·색상·행동이 완전히 같거나 정확하다고 보장할 수 없다. 프롬프트에는
캐릭터·그림체보다 원문 근거가 있는 사물과 행동을 먼저 넣는다. 이름만 나열하지 않고
행동 주체, 물건과의 접촉, 완료된 상태를 기술하도록 지시한다.

원문 인용은 근거 검사에만 사용하고 그림 프롬프트에 넣지 않는다. 대사는 기존 화면에서
별도 표시한다. OCR는 고신뢰 문자를 검사하지만 오탐·미탐이 있으며, 국소 복원으로 사물이
변형될 수 있다. 시각 검사 모델도 오탐·미탐이 있어 `requires_confirmation=true`를
유지한다. 사람이 사물 존재·행동·순서·색상·감정까지 확인해야 한다.

기본 이미지 모델은 Cloudflare FLUX.1 schnell이며 `.env`에서 IMAGE_PROVIDER=openai를 선택한 경우에만 OPENAI_IMAGE_MODEL(또는 기존 IMAGE_MODEL)을 사용한다. 공급자 전환을 자동으로 수행하지 않는다.

## Cloudflare 전용 생성 경로 — 2026-11-10

`IMAGE_PROVIDER=cloudflare`이면 장면 구성은 원문 순서에 따른 코드 분배를 사용한다.
그림 명세·생성·검토에 Groq/OpenAI를 호출하지 않는다. 기존 Cloudflare 키를 사용한다.
장면 모델은 선택 설정 `CLOUDFLARE_SCENE_MODEL`로 바꿀 수 있으며 현재 기본값은
`@cf/meta/llama-3.3-70b-instruct-fp8-fast`이다. `.env.example`만 추가했고 실제 `.env`는 수정하지 않았다.
공식 JSON Schema 모드 지원 모델을 기본으로 사용한다. 운영 전 모델 가용성과 대체 모델의 JSON 호환성을 확인한다. 모델 장애 시 구식 번역 프롬프트로 조용히 대체하지 않는다.

규칙·검사는 `scene_prompting.py`, 공급자 연결은 `providers.py`, 네 장면 생성·임시 캐시는
`comic_images.py`에 있다. 내부 장면 자료형은 공개 OpenAPI에 추가하지 않았다.

공식 규격: [FLUX.1 schnell](https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/),
[Cloudflare JSON 모드](https://developers.cloudflare.com/workers-ai/features/json-mode/).

모든 API 경로·요청·응답 필드·해시·근거 번호·확인 플래그는 기존 구조를 사용한다.
`planning_mode=deterministic`, 사용자 확인 안내는 기존 `notices`에 담는다.
Cloudflare의 `status=generated`는 생성과 파일 디코딩 검사를 마친 상태이며,
표준 만화는 보조 시각 검사도 수행하지만 내용의 완전한 일치를 보증하지 않는다. 표준 만화의 문자 탐지는 로컬 OCR가 담당하며, OCR 실행 실패는 status=failed이다. `requires_confirmation=true`를
유지하므로 표시·저장 전에 사용자가 실제 사건과 맞는지 확인하는 흐름이 필요하다.
`rejected` 상태는 표준 만화에서 글자 또는 시각 검사 불일치가 반복된 경우와 기존 다른 공급자의 검토 거절에 사용한다.
대화·일기 생성의 Groq 호출과 100초 일기 예산은 기존 동작을 유지한다.


## 그림 품질 검사와 짧은 말풍선

- `CLOUDFLARE_COMIC_REVIEW_MODEL`의 기본값은 `@cf/meta/llama-4-scout-17b-16e-instruct`이다. 기존 Cloudflare 키를 사용하며 Groq/OpenAI로 우회하지 않는다.
- 기본 외부 호출은 장면 작성 1회 + 이미지 4회 + 시각 검사 4회이다. 제한된 재생성 시 이미지·검사가 최대 1회씩 추가될 수 있다. 일시적 5xx HTTP 재시도는 별도로 최대 1회이며 180초 잔여 예산을 공유한다. 시각 검사는 컷별 최대 35초이다. 호출 한도/비용과 첫 이미지 요청의 대기 시간을 고려한다.
- `comic_review.py`는 그림 검사 스키마, 사물 개수 대조, 재생성용 고정 지침을 관리한다. 검사 결과는 원문·공급자의 자유 문장과 함께 로그에 남기지 않는다.
- 그림 자체는 글자 없이 생성한다. 말풍선은 OCR/시각 검사가 끝난 뒤 FE에서 표시한다. 검사에서 말풍선 문자를 지우는 문제가 생기지 않는다.
- 개발 UI의 `comicBubble(caption, childSources)`는 아이 원문과 장면 글에서 그대로 확인되는 40자 이하 문장을 사용한다. 완결된 짧은 인용을 고르고 긴 문장은 자르거나 바꿔 쓰지 않는다.
- 명시적인 말은 `speech`, 마음속 생각은 `thought`로 구분한다. 생각 풍선은 점선과 둥근 꼬리로 표시한다. 친구/부모/교사의 말, 명확히 부정된 발언, AI 질문은 제외한다.
- 출처가 없거나 화자가 불분명하면 말풍선을 비운다. 인용이 없는 서술문을 마음대로 아이의 대사로 바꾸지 않는다. 한국어 화자·정정 규칙은 보수적인 휴리스틱이므로 사용자 확인이 필요하다.
- FE는 `/api/diary`의 아이 원문 sources 또는 보관한 child 메시지를 공급한다. `/api/visual-story`의 sources는 일기 문장 번호이므로 아이 발언 번호와 혼동하지 않는다. 개발 화면에서는 대화 원문 스냅샷을 로컬 상태로 넘기며 공개 API 필드를 추가하지 않았다.
- 화면과 HTML 내보내기에서 동일한 추출/이스케이프 함수를 사용한다. 전체 아이 원문을 내려받기 HTML에 포함하지 않고 선택된 말풍선만 표시한다. 다른 FE에서는 이 표시 로직을 연결해야 한다.

공식 모델 규격: [Cloudflare Llama 4 Scout](https://developers.cloudflare.com/workers-ai/models/llama-4-scout-17b-16e-instruct/).
