# 확인한 일기 → 그림책·4컷 만화 (AI v1.2)

## 이번에 추가한 기능

대화로 작성한 일기의 내용을 사람이 확인한 후, 그림책과 4컷 만화의 장면 글을 구성하고 장면별 그림을 생성한다. 기존 텍스트·음성 대화, 일기 API는 유지한다.

- 그림책: 원문 조각 수에 따라 1~6페이지. 기본 요청은 최대 4페이지이다.
- 4컷 만화: 정확히 4컷, 왼쪽 위→오른쪽 위→왼쪽 아래→오른쪽 아래 순서이다.
- 입력이 짧으면 같은 장면을 반복한다. 새로운 사건, 결말, 대사를 지어내지 않는다.
- 글은 확인된 일기의 문장들을 그대로 연결한다. 모델에게 새 캡션을 쓰게 하지 않고 원문 번호의 묶음만 받는다.
- 그림책은 수채화 삽화, 만화는 단일 컷의 또렷한 선·평면 색을 사용한다.
- 글은 이미지 밖에서 FE가 표시한다. 이미지 안에는 한글 캡션이나 말풍선을 생성하지 않는다.
- 그림마다 모델 검토를 거치며 거절 또는 실패 시 원문 글은 유지한다.

**이 파일은 AI 기능 추가 안내다.** FE 화면·완성된 PDF·4컷 합본 PNG를 만드는 코드는 포함하지 않는다. AI는 장면별 글·그림과 layout을 반환하고 FE가 페이지 또는 2×2 격자로 표시한다. BE는 결과·이미지를 저장한다. 실제 유료 생성 결과와 장면별 캐릭터 일관성은 아직 검증하지 않았다.

## 적용할 파일 — 이 변경분만 복사

기존 AI 저장소 루트에 다음 파일을 같은 위치로 반영한다. 직접 수정한 파일은 비교 후 병합한다.

| 파일 | 변경 |
| --- | --- |
| server.py | 수정: v1.2 및 API 2개 추가 |
| visual_models.py | 추가: 그림책·만화 요청/응답 자료형 |
| visual_story.py | 추가: 장면 구성·이미지 생성·검토 |
| tests/test_diary.py | 수정: API 목록 검사에 새 경로 추가 |
| tests/test_visual_story.py | 추가: 새 기능 검사 |
| docs/VISUAL_STORY.md | 추가: 이 안내서 및 변수 설명 |
| docs/API_CONTRACT.md | 수정: v1.2 연동 규격 보충 |

`.env`, `.git`, requirements.txt, engine.py, models.py, prompts.py, voice.py는 이 패치에 포함하지 않는다. 새 패키지 설치나 필수 환경 변수 추가도 없다. 기존 음성 지원 v1.1 코드가 설치되어 있어야 한다.

서버가 실행 중이면 Ctrl+C로 종료한 후 실행한다.

```sh
source .venv/bin/activate
python server.py
```

Windows는 `.\.venv\Scripts\python.exe server.py`로 실행한다. http://127.0.0.1:8002/docs 를 새로고침해 `/api/visual-story`와 `/api/visual-story/image`가 보이는지 확인한다.

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
| imageUrl | 생성·검토를 통과한 PNG 데이터 URL 또는 null |
| status | generated / rejected / failed / mock |
| error | 실패 안내 또는 null |
| requires_confirmation | 생성 그림을 사람이 확인해야 한다는 표시 |
| mock | 체험 모드 여부 |

HTTP 200이라도 status가 generated인지 확인한다.

- generated: imageUrl을 표시하고 사용/제외를 확인한다.
- rejected: 검토에서 거절한 그림은 반환하지 않는다. 글은 유지한다.
- failed: 모델 요청 또는 검토 처리 실패. error를 안내하고 해당 장면만 재시도한다.
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

BE는 API 결과의 PNG 데이터 URL을 바이너리로 디코딩해 기존 파일 저장소에 저장하고 FE용 URL로 바꿀 수 있다. 일기 글이 수정되면 구성을 다시 생성하고 이전 그림은 새 일기에 자동 연결하지 않는다. 응답이 늦게 도착했을 때 diary_hash와 페이지 버전을 비교해 오래된 결과를 폐기한다.

## 제한·오류

- 입력 일기: 공백을 제외하고 비어 있지 않아야 하며 필드 길이는 최대 6,000자.
- 원문 조각: 최대 80개. 긴 일기를 임의로 잘라 버리지 않고 오류를 반환한다.
- 이미지 source_ids: 1~80개, 유효한 연속 번호를 오름차순으로 전달.
- 400: confirmed=false 또는 확인 표시 누락.
- 409: diary_text가 diary_hash와 일치하지 않음. 구성을 다시 요청.
- 422: 형식·길이·근거 번호 오류.
- 모델 구성 오류는 planning_mode=fallback으로, 이미지 처리 오류는 HTTP 200/status=failed로 반환한다. BE는 상태 필드를 반드시 확인한다.

이미지 한 장마다 이미지 생성 1회와 텍스트 모델의 시각 검토 1회가 실행된다. 기본 그림책 4장과 만화 4장을 모두 만들면 최대 8장 생성 비용이 발생한다. 반복 컷은 재사용한다. 이미지별 생성 180초+검토 45초의 타임아웃 설정을 사용하므로 BE에서 장면 단위 대기/비동기 작업을 구성한다. 모든 장면을 한 요청에 몰아 생성하는 서버 배치 API는 없다. 제한 없이 병렬 호출하지 말고 호출 수와 대기 화면을 관리한다.

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

기존 34개와 새 검사 29개, 총 63개 검사를 통과했다. 실제 API 대신 테스트 응답을 사용했으며 실제 이미지 생성·실제 계정의 모델 권한·FE 렌더링은 검증하지 않았다. API 키를 읽거나 새 이미지 비용을 발생시키지 않았다.

글의 원문 보존은 코드에서 검사한다. 그러나 그림 속 시각적 세부가 원문과 완전히 일치한다고 보장할 수는 없다. 모델 검토와 사람의 확인이 필요하다. 장면마다 독립적으로 그리므로 캐릭터 모습이 완전히 같다는 보장도 없다. 외모가 미정이면 중립 실루엣을 사용하도록 지시했다.

기존 IMAGE_MODEL 설정은 그대로 사용한다. 공식 안내에 gpt-image-1.5의 2026-12-01 종료 예정이 표시되어 있으므로 장기 운영 전 지원 모델로 별도 검증·전환해야 한다. 이번 패치는 모델을 자동 변경하지 않는다.

참고: [OpenAI 이미지 생성 API](https://developers.openai.com/api/reference/resources/images/methods/generate), [기존 이미지 모델 안내](https://developers.openai.com/api/docs/guides/image-prompting).
