# BE 통합 검증 기록 — 2026-11-08

> 이 문서는 1차 작업 기록이다. 125684e 이후의 수정과 최신 검증은 [요구사항 재점검](REQUIREMENTS_AUDIT.md)을 따른다.

## 범위와 재현

작업 시작 상태는 main / 94c3e20이며 미커밋 변경은 없었다. 지시문에 기재된 cca79eb로 되돌리지 않고 현재 구현을 사용했다. 커밋·푸시는 수행하지 않았다. 기존 API 필드·모델·공급자·프롬프트는 변경하지 않았다. 명확한 종료 의사를 우선하는 engine.py 처리를 추가했다.

- `scripts/verify_integration.py`: 가상 대화, 정확한 BE 응답 필드, 출처·페이지·확인 플래그, 4컷·짧은 원문 재사용 검사. 성공 이미지의 base64를 디코딩하고 Pillow로 실제 파일 형식·크기를 검사한다.
- `engine.py`: 명확한 종료 문장 전체 일치 시 모델 없이 finished=true를 반환한다. 부정·인용 문장은 기존 모델 경로를 유지한다. 이 경우 생성+검토 2회 호출을 생략하므로 비용·지연이 감소한다.
- `tests/test_integration_contract.py`: 실제 코드 경로에 가짜 공급자를 주입해 일기 계약, 공급자 오류와 fallback 구분, 성공·실패·거절이 섞인 컷 보존을 검사한다. 이 테스트를 실제 모델 결과로 해석하면 안 된다.
- README/API 문서: 기본 공급자 및 실제 타임아웃·오류 코드 설명 수정.
- `requirements-dev.txt`: 이미지 파일 검사용 Pillow 추가. 런타임 의존성은 그대로다.

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/verify_integration.py --images --output artifacts/integration/mock
# 외부 API 사용량 발생. 실제 공급자 설정과 키는 기존 .env에서 읽는다.
.venv/bin/python scripts/verify_integration.py --live --images --interval 20 --output artifacts/integration/live-paced-network
```

FastAPI TestClient로 실제 HTTP 라우트·직렬화와 외부 공급자를 검증한다. BE 서버나 Supabase를 호출한 종단간 검증은 아니다. 실행 종료 코드 0은 기록과 계약 assertion 완료를 뜻하며, 모든 모델 요청 성공을 뜻하지 않는다. JSON의 http_status, mock, fallback, planning_mode, status를 함께 확인해야 한다. 생성 품질과 인물 일관성은 사람이 별도 확인해야 한다.

## 결과 파일

각 `results.json`에는 가상 입력과 실제 응답 JSON, HTTP 코드, 요청별 초 단위 시간이 있다. 이미지 성공 시 data URL 원본과 디코딩 파일도 저장한다. API 키·계정 ID·원본 공급자 오류는 기록하지 않는다.

- `artifacts/integration/mock/results.json`: 모의 연결 검사.
- `artifacts/integration/live/results.json`: 샌드박스 네트워크 차단. 실제 모델 품질 근거에서 제외.
- `artifacts/integration/live-network/results.json`: 외부 연결 허용 후 연속 호출. 첫 네 질문 성공, 종료·일기와 이미지 요청은 Groq 한도 오류. 실제 장면 구성은 model 모드, 짧은 원문은 deterministic 모드.
- `artifacts/integration/live-paced-network/results.json`: 20초 간격의 재검증. 시간은 대기 간격을 제외한 요청 처리 시간이다.

## BE 연결 시 처리

기본 개발 주소는 `http://127.0.0.1:8002`다. 타 PC 주소·FE용 만화 URL은 정하지 않았다. BE 만화 생성·저장 API가 별도로 필요하다.

1. `/api/diary`의 sources.id는 전체 messages 위치이며 assistant 때문에 번호가 연속적이지 않을 수 있다. child 원문과 순서를 그대로 유지한다. 페이지는 최대 6개, imageUrl=null, requires_confirmation=true다.
2. `/api/visual-story`의 sources.id는 확인한 일기를 나눈 조각 번호다. 일기 출처 ID를 그대로 보내지 않는다.
3. `comic4.scenes` 네 개와 `grid_2x2`를 사용한다. `reuse_scene_id`가 있으면 원본 컷의 생성 결과를 재사용한다. 새 이미지를 네 번 호출할 필요가 없고 시간 경과를 뜻하지도 않는다.
4. `generated`만 이미지를 저장한다. `rejected`는 검토 거절, `failed`는 공급자·생성·검토 오류, `mock`은 실제 이미지 없음이다. 이미지 요청 HTTP 200만으로 성공 처리하면 안 된다. 한 컷 실패로 기존 성공 컷을 삭제하지 말고 scene_key로 분리 보관한다.
5. data URL은 영구 URL이 아니다. MIME을 확인하고 디코딩한 뒤 BE 저장소에 저장한다. 아이의 원본 그림과 AI 이미지를 별도 자산으로 관리한다. 일기 수정 후에는 다시 구성하여 diary_hash를 갱신한다.
6. 현재 이미지별 인물 참조 이미지나 고정 캐릭터 ID는 없다. 같은 인물의 외형 일관성은 보장되지 않는다. 단일 이미지 검토 통과와 컷 간 일관성은 다른 검사다.

입력 제한은 대화 60개·각 2,000자·전체 20,000자, 만화 일기 6,000자·최대 80조각, 기존 개별 이미지 1,500자다. BE 일기 20,000자를 조용히 6,000자로 자르지 않는다. 1차 연동은 한도 초과 시 원문을 유지하고 만화 생성을 보류하는 방안을 제안한다. 이후 사용자 승인으로 범위를 선택하거나 API 한도 확장을 BE와 합의해야 한다. 이번 작업에서 계약 한도는 변경하지 않았다.

ProviderRouter의 자동 재시도는 0회다. 텍스트 생성 60초+검토 60초, Cloudflare 이미지 묘사 60초+생성 180초+검토 60초로 순차 호출한다. 이 값은 SDK의 개별 타임아웃이며 전체 요청의 엄격한 마감 시간이 아니다. BE는 텍스트 타임아웃을 이미지에 그대로 적용하지 말고 여유 있는 비동기 작업·컷별 상태 저장을 협의해야 한다.

## 모델과 비용

로컬 설정은 텍스트 Groq `openai/gpt-oss-20b`, 이미지 Cloudflare `@cf/black-forest-labs/flux-1-schnell`(4 steps), 검토 Groq `qwen/qwen3.8-27b`다. `AI_MODE=openai`는 실제 호출을 뜻하며 OpenAI 공급자를 뜻하지 않는다. README의 이전 OpenAI 전용 설명을 수정했다.

질문·일기는 보통 텍스트 호출 2회, 고유 이미지 한 장은 텍스트 묘사 1회+이미지 생성 1회+비전 검토 1회다. 실제 토큰 사용량은 현재 API가 반환하지 않으므로 이 보고서에 실청구액으로 제시하지 않는다.

2026-11-08 공식 가격표 확인: GPT OSS 20B 입력 $0.075/백만 토큰, 출력 $0.30/백만 토큰이다. 예를 들어 총 입력 2,000·출력 500토큰이면 $0.00030이다(실측 아님). [Groq 모델 가격](https://console.groq.com/docs/model/openai/gpt-oss-20b)

FLUX는 512×512 타일당 $0.0000528+step당 $0.0001056이다. 1024×1024·4 steps 가정 시 이미지 생성만 $0.0006336/장, 4장 $0.0025344이며 텍스트·비전 검토 비용은 별도다. 실제 크기·무료 할당량·비전 사용량에 따라 달라지므로 총비용 확정값이 아니다. [Cloudflare 가격](https://developers.cloudflare.com/workers-ai/platform/pricing/)

## 정정·종료에 대한 발견

간격 재검증의 종료 요청은 `finished=false`, `fallback=true`로 추가 질문을 반환했다. 생성 후보/검토의 세부 내용은 수집하지 않아 어느 문구 때문에 거절됐는지는 확정할 수 없다. 명확한 종료 의사는 모델 검토 실패로 뒤집지 않도록 전체 문장 패턴을 우선 검사하는 수정을 적용했다. 부정·인용은 종료로 판단하지 않는 회귀 테스트를 추가했다. 모든 종료 표현을 규칙으로 포괄하지는 않으며 다른 표현은 기존 모델 판단을 따른다.

복잡한 정정·거절·종료가 포함된 일기는 HTTP 200, mock=false, fallback=true로 원문을 보존했고 BE 구조 검사를 통과했다. 이는 다듬어진 일기 생성 성공이 아니다. 과거 발언과 이후 정정이 원문 그대로 함께 포함되므로 사람 확인 없이 확정 일기로 저장해서는 안 된다. 자동으로 모순을 제거하는 변경은 원문 보존 정책을 훼손할 수 있어 적용하지 않았다.

## 수정 후 확인

`artifacts/integration/fixed-live/results.json`에서 종료는 finished=true, fallback=false, mock=false(0.002초)다. 이 종료 응답은 실제 모드의 로컬 규칙 처리이며 모델 생성 결과는 아니다. 단순 일기는 실제 모델 생성+검토로 1.717초에 `집에서 파란 블록을 쌓았다. 재미있었다.`를 반환했고 fallback=false, mock=false였다. pages 2개·sources [1,3]·null 이미지·확인 플래그 등 계약 검사를 통과했다.

자동 테스트: Python 92개, JavaScript 21개 통과. JavaScript 테스트는 PATH에 node가 없어 로컬 설치 `/Users/ohkw02/.nvm/versions/node/v24.14.1/bin/node`를 사용했다. 실제 BE 검증기를 실행한 것은 아니며 제공된 계약을 기준으로 AI 응답을 검사했다.

생성된 comic4-3은 JPEG 1024×1024, 142,726바이트로 전체 디코딩을 통과했다. 직접 확인한 이미지에는 연필을 든 아이와 동그라미가 있는 종이가 있고 글자·다중 패널은 없다. 핵심 사물은 보이나 중립 실루엣 대신 구체적인 머리·의상·얼굴이 그려졌다. 자동 검토 통과가 모든 프롬프트 제약이나 컷 간 인물 일관성을 보장하지 않는 사례다.

## 최종 실제 4컷 결과

| 컷 | 상태 | 시간(초) |
|---|---|---|
| comic4-1 | rejected | 5.1 |
| comic4-2 | rejected | 2.946 |
| comic4-3 | generated | 2.786 |
| comic4-4 | rejected | 5.263 |

4컷 요청 평균 4.024초, 최대 5.263초다. generated 1/4(25%), rejected 3/4(75%), failed 0/4다. 이 표본에서는 사용 가능한 이미지 미반환율이 75%이며 일반 실패율로 확장할 수 없다. 거절된 그림은 반환되지 않아 직접 원인을 확인할 수 없다. 성공 컷은 파일로 보존됐다. 최초 연속 실행의 4컷은 Groq 한도 오류로 failed 4/4였다.

기존 `/api/image` 최종 호출은 HTTP 503이며 응답은 `{"error": "cloudflare: 모델이 요청 형식을 지원하지 않습니다. 설정한 모델 이름을 확인해 주세요."}`이다. 기존 개별 이미지 경로의 실제 성공 검증은 남아 있다.

남은 문제: 복잡한 정정 일기의 fallback 빈도, 4컷 검토 거절률과 외형 일관성 개선, 기존 이미지 API의 성공 재검증, 실제 BE 검증기·저장 API 연동, 6,000/20,000자 한도와 이미지 작업 타임아웃 합의다. 1차 텍스트 계약 검사는 통과했지만 4컷을 배포 가능한 품질로 판정하지 않는다.
