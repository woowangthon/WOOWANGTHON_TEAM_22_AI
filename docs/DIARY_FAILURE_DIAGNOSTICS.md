# 일기 생성 실패 로그 분석 및 안전한 진단 보완

## 확인한 소스 범위

작업 기준은 로컬 `ai_talk` / `a4a0353e142ba03063b509d8348dcc58e85abfb4`이며 시작 시 미커밋 변경은 없었다. 적용 지침은 루트 `AGENTS.md`다. 코드와 기존 가짜 Provider 테스트를 확인하고 원격 refs도 읽기 확인했다.

AI 원본 저장소는 `woowangthon/WOOWANGTHON_TEAM_22_AI`다. 최초 분석 시 원격 main은 `a4a0353`, 원격 ai_talk는 `d94a4a3`였고 이 저장소에서는 `f29871e`를 찾지 못했다. 이후 사용자가 `f29871e`는 별도 비공개 Render 배포 저장소의 커밋이며 Render 배포도 확인했다고 설명했다. 아래 분석은 AI 원본 a4a0353 코드 기준이며 배포 저장소의 소스는 이번 작업에서 직접 대조하지 않았다. 이 진단 변경은 AI 원본 main에 반영하고, 배포 저장소 반영과 실제 오류 확인은 팀이 진행한다.

## 제공된 로그의 의미

| 로그 | 현재 코드에서 발생하는 조건 | 이 로그만으로 알 수 없는 것 |
| --- | --- | --- |
| `review_rejected attempt=1` | 최초 생성 성공, 문장 수·길이·child source ID 검증 통과, Review 형식 파싱 성공, `accepted=false` | 어떤 사실·표현 때문에 검토가 거절됐는지. 한도 오류를 의미하지 않는다. |
| `review_failed attempt=2` | 두 번째 후보(재작성) 생성·로컬 검증 이후 검토 호출에서 예외 발생 | 429·인증·timeout·JSON/스키마·빈 응답·불완전 응답·예기치 않은 코드 오류 중 무엇인지 |
| `generation_failed attempt=1` | 최초 후보를 얻기 위한 adapter.parse 호출 중 예외 발생 | HTTP/공급자 오류인지, 응답 형식·완성도 문제인지 |

`review_failed`는 검토가 `accepted=false`를 반환한 것과 다르다. 전자는 검토 결과를 정상적으로 얻지 못했고, 후자는 정상 검토의 거절이다. `generation_failed` 역시 무조건 JSON 오류를 뜻하지 않는다. adapter 초기화·키 설정 문제와 공급자 실패도 해당 호출에서 예외가 나면 포함된다.

현재 코드에서 최초 거절은 시간 여유가 있으면 재작성·재검토로 이어질 수 있다. 두 번째 검토에서 예외가 나면 `raise`로 엔진 호출이 종료되며 최초 생성으로 다시 돌아가지 않는다. 따라서 하나의 엔진 실행에서 `review_failed attempt=2` 뒤에 `generation_failed attempt=1`이 이어지는 것은 불가능하다. 두 요청의 중첩/재시도, 다른 실행 또는 배포 코드 차이 등을 구분해야 한다. 시각과 attempt 값만으로 요청을 묶지 않는다.

예산 내 공급자 실패는 ProviderRouter가 변환한 `ProviderError`라면 기존 HTTP 503 `{"error":"..."}`로 전달된다. 변환되지 않은 SDK/자료형 오류는 기존 502다. 검토 거절·출처 오류·전체 예산 소진은 원문 fallback으로 처리한다. 화면의 `초안 실패: AI 응답 실패`는 이 AI 저장소의 정확한 오류 문자열이 아니며, BE·FE가 원래 오류를 어떻게 표시했는지는 확인하지 않았다.

## 필요한 진단 보완

판단 근거가 없는 상태에서 모델·프롬프트·재시도·fallback 정책을 바꾸지 않았다. 다음 정보만 서버 내부 로그에 추가했다.

- `request_id`: 요청마다 서버가 생성하는 임의 UUID hex. 요청 헤더·사용자 ID·원문에서 만들지 않는다. HTTP watchdog, 엔진, fallback이 같은 ID를 공유한다. 새로운 요청에는 새로운 ID를 부여한다.
- `stage`, `attempt`: generation/review와 1차/2차를 구분한다.
- `reason`: 허용 목록으로 정규화한 고정 분류만 출력한다.
- `provider`, `status`: 허용된 공급자명과 숫자 upstream HTTP 상태만 출력한다. upstream 429도 이 AI의 HTTP 응답은 기존 정책대로 503일 수 있다.

| reason | 의미 |
| --- | --- |
| `rate_limit` | upstream 429, 알려진 결제/잔액 오류 코드는 없음. Free 플랜 여부나 어떤 한도를 초과했는지는 이 값만으로 모른다. |
| `quota_exhausted` | 알려진 잔액·청구 한도 오류 코드 |
| `authentication` / `permission` | upstream 401 / 403·404 |
| `invalid_request` / `provider_server_error` | upstream 400 / 5xx |
| `timeout` / `connection` | 개별 호출 timeout / 연결 실패 |
| `response_schema_invalid` | JSON 또는 Pydantic 응답 스키마 불일치 |
| `response_truncated` / `response_filtered` | Groq 응답 finish_reason이 length / content_filter |
| `response_incomplete` / `empty_response` | choices 없음·기타 불완전 종료 / 빈 본문·파싱 결과 |
| `configuration` | 필수 서버 설정 없음 |
| `provider_error` / `unexpected_error` | 기타 분류된 공급자 오류 / 아직 분류하지 못한 예외 |

예: `diary outcome=review_failed attempt=2 request_id=<임의32자리> stage=review reason=rate_limit provider=groq status=429`

`review_rejected`의 reason은 none이다. 이 검토는 여전히 bool만 반환하므로 구체적인 의미상 거절 이유는 기록되지 않는다. 원본 예외 문자열·traceback·공급자 응답 본문/코드·요청 헤더·API 키·대화·후보 일기는 로그에 넣지 않는다. 알 수 없는 외부 값은 고정 분류 또는 unknown/none으로 바꾼다. request_id와 오류 메타데이터는 BE 응답 JSON이나 헤더에 추가하지 않았다.

## 변경 및 검증 범위

수정 파일은 `engine.py`, `providers.py`, `server.py`, 신규 `diagnostics.py`, 신규 `tests/test_diary_diagnostics.py`, watchdog 상관관계 검사 보강 `tests/test_diary_budget.py`, 이 문서다.

진단 테스트 41개는 실제 SDK에 MockTransport를 연결하여 생성 1차·검토 1차·검토 2차에서 한도·잔액·인증·잘못된 요청·공급자 5xx·timeout·연결·잘못된 JSON·잘못된 스키마·빈 응답·출력 잘림·필터·choices 없음을 검증한다. 실제 세 로그와 동일한 순서를 두 HTTP 요청으로 재현하여 최초 두 로그의 request_id는 같고 마지막 로그는 다른 것을 확인한다. 오류 메타데이터가 JSON에 추가되지 않고 원문·키·후보·외부 request ID가 로그에 노출되지 않는 것도 확인한다.

기존 100초 예산, 출처 보존, 정상 일기·정정·짧은 답변·거절·fallback·Provider 오류 경로도 기존 테스트로 유지한다. 사용자 후속 요청에 따라 진단 보완을 AI 원본 저장소 main에 커밋·푸시한다. 실제 Groq 호출·유료 작업·Render 재배포는 수행하지 않는다.

실행 결과: `.venv/bin/python -m pytest tests/test_diary_diagnostics.py -q` 41개 통과, `.venv/bin/python -m pytest -q` 전체 188개 통과, `git diff --check` 통과.
