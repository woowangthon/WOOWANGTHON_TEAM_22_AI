# 통합 지시문 재점검 — 2026-11-08

기준 문서: `AI_오경원_통합작업_지시문.txt` 전체. 시작 상태는 main / 125684e (`be요구사항 구현`), 미커밋 변경 없음이었다. 이전 검증은 94c3e20 기반이므로 이번 결과와 구분한다. 사용자 기존 `.env`·모델 선택을 덮어쓰지 않았다. 커밋·푸시는 수행하지 않았다.

## 요구사항 대응표

| 지시문 요구 | 코드·검증 근거 | 판정 |
|---|---|---|
| 최신 브랜치·HEAD·미커밋 확인, 기존 구현 재사용 | main / 125684e, engine/providers/visual_story 유지 | 완료 |
| /api/chat 필수 4필드 및 요청 메시지 유지 | models.py 변경은 MIME 주석뿐, 실제 응답 필드 검사 | 유지 |
| /api/diary 필수 6필드·최대 6페이지 | 최대 60메시지·20생성문장·20,000자 경계 테스트 | 완료 |
| child 원문의 전체 메시지 0-based 인덱스·순서 보존 | sources 전체 목록 비교; assistant 포함 60메시지 테스트 | 완료 |
| 페이지 출처 유효성·imageUrl=null·확인 필수 | verify_diary 및 실제 응답 검사 | 완료 |
| 이전 맥락·짧은 답·정정·부정·종료 | 가상 연속 대화, 정정/거절·명확한 종료 회귀 검사 | 실제 결과 아래 별도 |
| 반복 질문 감소 | 문장부호·공백 정규화 후 이미 한 동일 질문 차단, 대체 질문 중복 회피 | 보강 |
| 사실 왜곡 없는 일기 구성 | 최종 정정과 대화 제어 발언 처리 프롬프트 보강; 검토 불합격 시 원문 보존 | 보강, 모델 품질은 별도 |
| 생성 오류와 fallback 구분 | 오류는 기존 503; 검토 거절 일기는 fallback=true; mock 구분 | 유지 |
| 정확히 4장면·2×2 | VisualStoryService.plan 및 실제 plan 응답 | 완료 |
| 4장면 실제 이미지 호출, 기존 /api/image 검증 | recheck-live/results.json에 개별 요청·응답·처리 시간 | 실제 결과 아래 별도 |
| generated/rejected/failed/mock 구분 | 검토 미완성은 이제 failed; 정상 accepted=false만 rejected | 수정 |
| 이미지 data URL 디코딩·파일 형식 | image_data.py: 엄격한 base64, PNG/JPEG, 전체 파일 검증·디코딩 | 보강 |
| 인물·상황·행동 일관성 | 기존 원문 맥락·자동 검토 유지, 성공 이미지 직접 확인 | 인물 고정 보장 불가 |
| 짧은 원문 재사용 | 원문 1/2/3조각 검사, reuse_scene_id 및 JS 실제 재사용 흐름 | 완료 |
| 컷별 부분 실패 시 성공 보존 | Python 혼합 상태 테스트, JS 부분 실패/재시도 테스트 | 완료 |
| 형식·시간·실패율·실제 JSON | 검증 파일·summary·아래 결과 | 완료 |
| FE 직접 연결/새 BE API 임의 확정 금지 | 제품 FE/BE 파일·라우트 추가 없음; 기존 로컬 개발 화면 유지 | 준수 |
| source_ids 의미 분리·data URL 영구 저장 아님 | API_CONTRACT/VISUAL_STORY/이전 통합 보고서 | 문서화 |
| 6,000/20,000자 차이 해결 협의 | 한도 유지; 초과는 보류하고 원문 보존 제안 | BE 합의 대기 |
| 텍스트 timeout을 이미지에 재사용 금지 | 묘사60+생성180+검토60초 문서 수정 | 문서화, BE 구현 별도 |
| 원본 아이 그림과 생성 이미지 별도 자산 | AI는 저장하지 않음; BE 저장 책임 명시 | BE 구현 별도 |
| 모델·공급자·비용 공유 | 실제 모델 설정은 results.json, 비용 산식은 INTEGRATION_VERIFICATION.md | 문서화 |

## 이번에 고친 문제

1. Groq의 length/content_filter 종료나 빈 OpenAI 검토 응답을 정상 거절로 취급하던 처리를 실패로 변경했다. `failed`와 `rejected`의 구별이 이제 코드와 문서에서 일치한다.
2. JPEG/PNG 시그니처만 있던 손상 파일도 통과할 수 있었다. 공통 `image_data_url`로 전체 파일을 검사하고, 16메가픽셀·base64 28MB 제한을 적용한다. 기본 1024×1024 결과는 그대로 통과한다. Cloudflare, OpenAI 및 이전 어댑터 경로에 적용했다. Pillow를 개발 전용에서 런타임 의존성으로 옮겼다.
3. 모델 검토가 실수로 승인해도 이전과 동일한 질문이면 fallback을 사용한다. 의미만 같은 다른 표현까지 완벽히 탐지하는 기능은 아니다. 대체 질문도 소진되면 마지막 비질문 안내를 유지하며 자동 종료로 바꾸지 않는다.
4. 정정 전 발언을 수정하는 것과 종료/거절 표현을 일기에 옮기지 않는 것을 잘못된 누락으로 간주하지 않도록 생성·검토 지침을 맞췄다. sources의 원문은 여전히 전부 보존한다. 프롬프트 개선이 모든 왜곡을 막는다는 보장은 없다.
5. 검증 도구가 이미지 검사 전에 응답을 저장하도록 바꿨다. 실패해도 원본 응답이 남고, 공급자 호출 단계별 성공/실패와 시간을 기록한다. API 키·원본 공급자 오류·거절된 이미지는 저장하지 않는다. summary는 HTTP 성공과 이미지 성공·fallback을 분리한다.
6. VISUAL_STORY의 PNG 전용 안내, 구버전 검증 개수, 공급자와 타임아웃 설명을 갱신했다. Cloudflare HTTP 400을 특정 모델 문제라고 단정하던 안내도 입력·모델·계정 상태 확인으로 수정했다. 실제 오류의 원인을 추정해 모델을 바꾸지는 않았다.

추가 외부 재시도나 생성 횟수는 도입하지 않았다. 이미지 전체 디코딩 CPU 작업이 추가되고 모델 호출 수는 동일하다. 기존 필수 JSON 필드·자료형·입력 제한·오류 HTTP 코드는 유지했다.

## 재현

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --test tests/*.mjs
.venv/bin/python scripts/verify_integration.py --images --output artifacts/integration/recheck-mock
.venv/bin/python scripts/verify_integration.py --live --images --interval 20 --output artifacts/integration/recheck-live
```

실제 호출은 가상 데이터만 사용하며 비용이 발생한다. `results.json`에 요청과 응답 원본, HEAD·dirty 상태·공급자 설정·초 단위 시간이 있다. `stages`는 parse/이미지 생성/검토 단계를 구분한다. 검증 도구 종료코드 0은 모델 품질 통과를 뜻하지 않는다. 모델별 토큰 사용량과 계정 청구액은 아직 수집하지 않으므로 예상 비용을 실청구액으로 제시하지 않는다. 가격은 이전 보고서에 인용한 공식 페이지를 기준으로 다시 확인할 수 있다.

BE 서버·DB·실제 BE 검증기는 이 저장소 밖에 있으므로 연결했다고 주장하지 않는다. 대화/일기 구조 통과와 최종 서비스 통합 완료를 구분한다.

## 최종 재검증 결과

Python 114개, JavaScript 21개 통과. mock 검증은 실제 모델 품질과 분리했다.

| 요청 | HTTP | 결과 | 시간(초) |
|---|---|---|---|
| followup | 200 | finished=false, fallback=false | 1.756 |
| short | 200 | finished=false, fallback=false | 2.479 |
| correction | 200 | finished=false, fallback=false | 1.558 |
| refusal | 200 | finished=false, fallback=false | 2.179 |
| finish | 200 | finished=true, fallback=false | 0.006 |
| diary | 200 | fallback=true | 2.204 |
| plan | 200 | model | 0.968 |
| short_plan | 200 | deterministic | 0.007 |
| comic4-1 | 200 | rejected | 3.793 |
| comic4-2 | 200 | rejected | 4.621 |
| comic4-3 | 200 | generated | 4.005 |
| comic4-4 | 200 | failed | 2.366 |
| legacy_image | 200 | rejected=false | 3.393 |

4컷 평균 3.696초, 최대 4.621초. generated 1/4, rejected 2/4, failed 1/4로 이미지 미반환율은 75%다. 4개 샘플의 결과이며 일반적인 품질/실패율 추정값은 아니다. 컷4는 Groq 영문 묘사 완료 후 Cloudflare 생성 단계에서 실패했다. 컷1/2는 생성 성공 후 완성된 검토가 거절했다.

기존 `/api/image`는 이번에 HTTP 200, rejected=false로 성공했다. JPEG 1024×1024, 77,067바이트이며 전체 디코딩을 통과했다. 4컷 중 성공 이미지도 JPEG 1024×1024다. 그림과 실응답은 다음에 보관했다.

- [실제 전체 요청·응답 JSON](../artifacts/integration/recheck-live/results.json)
- [모의 전체 요청·응답 JSON](../artifacts/integration/recheck-mock/results.json)
- [성공한 3번 컷](../artifacts/integration/recheck-live/comic4-3.jpg)
- [기존 개별 이미지](../artifacts/integration/recheck-live/legacy_image.jpg)

이번 3번 컷은 `종이에 동그라미를 그렸다. 책을 펼쳤다.` 두 조각을 묶은 장면이다. 직접 이미지에서 종이·연필·펼친 책은 확인했으나 선 일부가 끊겨 동그라미와 행동이 선명하지 않다. 생성 상태는 자동 검토의 통과 표시이며 제품 품질 보증이 아니다. 네 컷 모두 인물이 성공적으로 나온 표본이 아니므로 컷 간 외형 일관성은 확인할 수 없다.

실제 정정 대화는 이후 블록 질문으로 이어졌고 종료는 finished=true였다. 복잡한 일기는 여전히 fallback=true다. 새로운 지침으로 항상 다듬어진 일기가 나온다고 주장하지 않는다. fallback 원문은 정정 전의 말과 뒤의 정정을 함께 담으므로 사람이 확인해야 한다. 기본 단순 일기의 실제 성공은 이전 fixed-live/results.json에 있으나 이번 복잡한 시나리오와 별도 표본이다.

## 남은 작업의 경계

AI 저장소에서 확인된 분류·파일 검증·반복 질문·문서 오류는 수정했다. 4컷 모두 통과하는 품질과 인물 외형 고정은 미완료다. 거절률을 낮추려고 검토를 끄거나 거절된 이미지를 정상 결과로 반환하지 않았다. 현재 이미지 모델은 장면마다 독립 생성하며 참조 캐릭터 전달이 없어, 일관성을 확정하려면 참조 이미지 지원 공급자/입력 설계 검증이 추가로 필요하다.

BE 만화 생성/저장 API, 6,000/20,000자 한도 합의, 이미지 비동기 작업 timeout 및 원본 그림/생성 그림 자산 분리는 BE와 협의할 항목이다. 이 저장소에서 FE 주소를 정하거나 BE 구현을 완료한 것으로 표시하지 않았다. 실제 API 키·계정 ID가 새 문서/검증 파일에 들어가지 않았음을 검사했다.
