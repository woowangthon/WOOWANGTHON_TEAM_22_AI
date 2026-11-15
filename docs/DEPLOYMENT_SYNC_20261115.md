# 제출 AI와 배포 코드 비교

2026-11-15 기준. 제출 브랜치는 `origin/main`의
`5e98abea8d65dd0847aba4fda161bf912bde8969`에서 시작했다.
기존 `ai_cs@f525208`은 PR #5로 main에 병합되어 있으며 기존 작성자와 커밋 이력을 유지한다.

비교 기준은 [Render 통합 코드 954ddc7](https://github.com/gichan8420/today-and-near-render/tree/954ddc7ccafab2d012288cdbab341a144a183e18/WOOWANGTHON_TEAM_22_AI)다.
실제 Render Live SHA는 미확인이므로 이 커밋과 운영 프로세스의 완전한 동일성을 단정하지 않는다.
이번 작업에서는 운영 배포, DB, 환경변수, 실제 모델 호출을 변경하거나 실행하지 않았다.

## 반영한 배포 동작

- 생성 원본을 먼저 캐시에 보관하고 생성 잠금을 해제한 뒤 OCR을 실행한다.
  느린 OCR 중 같은 컷 조회와 다른 컷 생성이 가능하며 성공 컷을 다시 생성하지 않는다.
  OCR 실패 또는 잔여 시간 8초 미만에는 원본을 보존한다.
  OCR 자체 잠금, 생성 잠금 3초, 장면 계획 20초, 컷 처리 100초는 유지한다.
- OCR ONNX 내부/외부 스레드를 각각 1개로 제한한다.
- 우냥이의 임시 모델 실패 안내와 고정된 `schema_errors` 진단 코드를 반영한다.
  메시지·검증 입력·공급자 원문·알 수 없는 필드명을 로그에 넣지 않는다.
- Cloudflare HTTP는 환경 프록시를 자동 사용하지 않으며 이미지 생성 요청을 추가 재시도하지 않는다.
- 4컷 호출, 장면 프롬프트, 검증과 응답을 비교 기준과 일치시킨다.
  병합된 main에만 있던 `panel_count` 전달, 장면 인용 6,000자 허용,
  3단어 행동 허용, `rejected` 추가 안내, OCR 배열 길이 추가 검사는 배포 기준으로 되돌렸다.
  장면 인용은 1,000자, 실제 행동은 최소 4단어다. 전체 일기 입력 한도 6,000자는 유지한다.
  장면 계획 검증 실패의 기존 확정 캡션 대체 경로와 성공 컷 보존은 유지한다.

## 의도적으로 남긴 차이

배포 AI의 Python 파일과 requirements 총 20개 중 15개는 줄바꿈 정규화 후 정확히 일치한다.
나머지는 다음처럼 제품 동작과 실행·개발 보조 파일을 구분한다.

| 파일 | 차이와 이유 |
| --- | --- |
| `image_quality.py` | 기존 `_recognize`·`_is_lettering` 공통 함수와 설명만 유지한다. OCR 잠금·스레드·검사 조건·결과 처리 동작은 같다. |
| `comic_review.py` | Render에만 있는 미사용 `retry_hint`를 추가하지 않는다. 양쪽 실행 코드에 호출자가 없다. |
| `dev_voice.py` | 기존 `ENABLE_WORRY_DEMO=1` 및 localhost 조건의 개발 화면을 유지한다. 제품 API나 공개 FE 기능이 아니다. |
| `runtime.py` | Render의 worker 활성화 검사·시작 시 OCR 준비·준비 상태 경로를 포함하는 배포 팩토리다. 통합 저장소에서 관리한다. |
| `check_runtime.py` | Render Docker 빌드의 OCR 모델 파일·오프라인 검증용이다. 통합 저장소에서 관리한다. |

Render는 `runtime:create_runtime_app` 팩토리와 `ProviderRouter(comic_image_attempts=1,
cloudflare_http_attempts=1)`을 사용하고 요청 수신 전에 OCR 엔진을 준비한다.
이 저장소에서 일반 개발 실행을 준비할 때는 기존 requirements와 `prepare_ocr.py`를 사용한다.
일반 `server.py` 실행이 Render의 worker gate와 readiness 설정까지 제공하는 것은 아니다.
운영 설정이나 키를 복사하지 않는다.

## 검증과 한계

BE `.venv` 인터프리터와 기존 로컬 OCR 패키지로 검사했다. 외부 HTTP·운영 환경파일 접근을
차단한 검사기에서 합성 공급자 응답과 합성 DB를 사용했다.

- OCR/캐시 집중 검사: 46개 통과. 느린 OCR 중 동일 컷 재조회·다른 컷 생성과 공급자 호출 횟수 포함.
- 우냥이/기존 진단: 69개 통과. SDK 고정 진단 코드 검사 5개 통과.
- 4컷 배포 계약·장면 검증·기존 시각화: 49개 통과.
- 최종 AI Python 전체 회귀: 303개 통과, 실패 0개. 일기·음성·개발 화면·공급자 계약 포함.
- BE↔AI 교차 검사: 103개 통과. 실제 로컬 OCR을 준비하고 우냥이 대화, 성공/실패/unknown,
  기존 ID 조회, DB 기록 실패 후 결과 보존을 검사했다. BE·AI OpenAPI와 WorryAction은 배포 기준과 같다.
- 기준 main 전체 검사에서 발견한 기존 vision 테스트 2개는 실제로 검토를 호출하는 그림책 경로로 수정했다.
  4컷은 이미 검토 없이 결과를 보존하는 경로이므로 기존 테스트가 외부 Cloudflare 호출로 빠졌으며,
  검사기의 HTTP 차단으로 실패했다. 제품 코드의 새 실패가 아니다.

실제 모델 품질·비용·운영 지연시간, Linux Docker 실행, Render Live SHA는 미검증이다.
프로세스가 사라지기 전 DB에 기록하지 못한 결과가 모든 경우에 복구된다고 보장하지 않는다.
