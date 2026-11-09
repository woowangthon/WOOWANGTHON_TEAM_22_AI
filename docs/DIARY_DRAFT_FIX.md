# 실제 일기 초안 원문 나열 원인 분석 및 수정 — 2026-11-09

> 이후 추가 수정: [100초 요청 시간 예산](DIARY_TIME_BUDGET.md)을 적용했다. 아래 4회 순차 대기 및 timeout 협의 설명은 최초 수정 기록이며, 현재 일기 API는 BE·FE 제한을 늘리지 않고 전체 예산 안에서 처리한다.

시작 상태는 `main`, HEAD `5395d90aba1e91f1575342a34b5120e496ed7001`, 미커밋 변경 없음이었다. 저장소와 상위 경로에서 적용할 `AGENTS.md`는 발견되지 않았다. `README.md`, `API_CONTRACT.md`, `BE_HANDOFF.md`, `MULTI_PROVIDER_SETUP.md`, `REQUIREMENTS_AUDIT.md`, 기존 실제 테스트 결과를 확인했다. `.env`와 모델 선택은 수정하지 않았다.

## 확인된 원인과 확인 범위

`artifacts/integration/recheck-live/results.json`의 `/api/diary` 기록은 HTTP 200, `mock=false`, `fallback=true`이며 반환 text는 child 발언의 줄바꿈 결합과 일치한다.

1. `DiaryCandidate` 생성 단계는 completed다. 이 기록의 원인은 공급자 연결·생성 실패가 아니다.
2. `Review` 호출도 completed다. 기존 엔진은 문장 수·길이·아이 발언 ID 검증에 통과해야 Review를 호출하므로 이 기록의 원인은 로컬 출처 ID 검증 실패도 아니다.
3. 이 조건에서 `fallback=true`가 되는 경로는 `Review.accepted=false`다. 따라서 저장된 실제 사례는 검토 거절 후 원문 fallback으로 전환된 것이다.
4. 당시 후보 본문과 검토의 accepted 값·이유가 기록되지 않아 어떤 사실 또는 문체 때문에 거절됐는지는 소급 확인할 수 없다. 최신 Render 요청과 응답·서버 로그는 제공되지 않았으므로 현재 웹사이트의 개별 요청 원인까지 단정하지 않는다.

기존 프롬프트에는 정정 반영과 종료/거절 생략 지침이 있으나, 의미가 불확실한 호응은 원문으로 남기도록 되어 있었다. 이 지침은 일기 속 '응' 등의 나열을 유도할 수 있고, 검토의 '주요 원문 내용 누락'·'불확실하면 false'와 함께 불필요한 거절을 일으킬 여지가 있다. 이는 코드에서 확인한 지침의 충돌이며, 과거 모델의 실제 거절 사유를 증명한 것은 아니다.

## 변경 내용

- `prompts.py`: 새 사실을 확정할 수 없는 호응을 일기에서 생략할 수 있도록 생성·검토 지침을 맞췄다. 명확한 짧은 답은 맥락에 연결하고, 질문 속 가정을 사실로 채택하지 않는다. 최종 정정은 정정 전후 ID로 뒷받침하며, sources 원문 전체 보관과 초안에 모든 발언을 넣는 것을 구분한다. 부정·시제·감정·정정·주요 사실 검토는 유지한다.
- `engine.py`: 검토 거절 시 원래 sources와 전체 conversation, 거절된 후보를 보내 한 번만 재작성하고 동일한 출처 검증과 검토를 적용한다. 두 번째 거절이나 잘못된 출처는 기존 원문 fallback이다. 공급자·응답 형식 오류는 기존 HTTP 오류로 전파하며 재시도하지 않는다. 승인된 초안만 `fallback=false`로 반환한다.
- 진단 로그는 `generation_failed`, `candidate_validation_failed`, `source_validation_failed`, `review_failed`, `review_rejected`, `accepted`와 시도 번호로 경로를 구분한다. 대화·초안·키·공급자 원본 오류는 로그에 쓰지 않는다. 거절·실패는 WARNING, 승인은 INFO다. 검토는 여전히 bool만 반환하므로 구체적인 의미상 거절 이유는 로그로도 알 수 없다.
- `scripts/verify_integration.py`: 향후 명시적으로 허용된 검증 실행에서는 검토의 accepted도 단계 기록에 남긴다. 이번 작업에서는 실제 호출 스크립트를 실행하지 않았다.
- `tests/test_diary.py`, `tests/test_diary_repair.py`: 가짜 Provider로 정상 및 보정·실패 경로를 검증했다.
- `docs/API_CONTRACT.md`, `docs/BE_HANDOFF.md`, `docs/MULTI_PROVIDER_SETUP.md`: 호출 횟수·대기 시간 설명을 갱신했다.

## 계약과 운영 영향

BE 요청·응답 모델과 라우트는 변경하지 않았다. `text`, `pages`, `sources`, `fallback`, `requires_confirmation`, `mock` 및 각 자료형을 유지한다. sources는 assistant를 포함한 전체 메시지 배열의 원래 인덱스와 아이 원문을 그대로 보존한다. 페이지는 최대 6개, imageUrl은 null, requires_confirmation은 true다. mock은 계속 원문 fallback을 반환한다.

정상 일기는 모델 호출 2회, 검토 거절 후 보정은 최대 4회다. 따라서 거절 경로의 토큰 사용과 지연이 증가할 수 있다. 현재 개별 호출 timeout 60초 기준으로 4회 순차 대기가 생길 수 있다. BE·FE나 Render의 timeout·설정은 변경하지 않았으며, 실제 운영 timeout 조정은 팀과 협의해야 한다. SDK 통신 재시도와 공급자 자동 전환은 추가하지 않았다.

## 검증 결과

외부 API 없이 아래를 실행했다.

```sh
.venv/bin/python -m pytest tests/test_diary.py tests/test_diary_repair.py tests/test_integration_contract.py -q
# 44 passed
.venv/bin/python -m pytest -q
# 132 passed
git diff --check
```

검증 사례: 정상 문어체 초안, 정정 전후 사실 및 출처 보존, 단순 호응·거절·종료를 포함한 대화, 명확한 짧은 답, 불확실한 답에 질문의 가정을 덧붙이지 않는 초안, 부정과 앞으로의 바람, 최초 거절 후 보정 성공, 반복 거절 후 원문 복원, 잘못된 최초/보정 출처 차단, 빈/공백/과도하게 긴 후보, 생성/검토/보정 단계의 공급자 실패, mock의 무호출, 로그에 대화 미포함, 기존 HTTP JSON 계약이다.

가짜 Provider는 준비한 초안과 검토 결과를 반환한다. 이 테스트는 엔진의 보정·검증·fallback과 계약을 확인하며 실제 Groq가 같은 일기를 생성하거나 승인한다는 증거는 아니다. 실제 Groq 호출·유료 작업·서버 배포·커밋·푸시는 수행하지 않았다. 수정은 위 HEAD 위의 미커밋 상태다.
