# Git에 연결된 VS Code 작업 폴더에 적용하기

이 절차는 이미 GitHub의 AI 저장소를 clone하여 VS Code에서 열어 둔 상황을 기준으로 합니다. 새로 `git init`하거나 원격 저장소를 다시 연결하지 않습니다. GitHub에는 파일이 자동으로 올라가지 않으며, 복사 → 실행 확인 → commit → push 순서로 반영합니다.

## 1. AI 저장소가 맞는지 확인

VS Code에서 `파일 → 폴더 열기`로 AI 저장소 폴더를 엽니다. 여러 저장소를 함께 열었으면 AI 저장소를 선택하세요. `터미널 → 새 터미널`에서 실행합니다.

```sh
git rev-parse --show-toplevel
git remote -v
git status
```

첫 결과는 로컬 AI 저장소 경로, 두 번째 결과는 팀의 AI GitHub 주소여야 합니다. FE 또는 BE 주소라면 해당 폴더가 아닌 AI 폴더를 다시 엽니다. 변경 중인 파일이 있으면 먼저 확인하고 별도 커밋하거나 백업한 뒤 적용하세요.

작업 트리가 깨끗하고 현재 브랜치에 원격 추적 설정이 있다면 최신 내용을 받습니다.

```sh
git pull --ff-only
```

충돌/추적 브랜치 오류가 나면 메시지를 해결한 다음 진행하세요. 빈 저장소의 첫 커밋 전에는 pull을 건너뛰어도 됩니다. 강제 덮어쓰기는 하지 않습니다.

새 작업 브랜치를 만듭니다. 같은 이름이 이미 있으면 다른 이름을 사용합니다.

```sh
git switch -c feature/ai-diary-api
```

## 2. 압축 파일 안의 내용 복사

`AI_전용_레포지토리.zip`을 풀고 **ai-repo 폴더 안의 내용물**을 AI 저장소의 최상위 폴더로 복사합니다. 압축을 푼 임시 폴더를 Git 저장소로 착각하지 않도록 주의하세요. macOS Finder에서 숨김 파일은 `Command + Shift + .`로 표시할 수 있습니다.

```text
내-AI-저장소/
├── .git/                 ← 기존 것을 그대로 유지
├── .gitignore            ← 기존 규칙에 새 규칙을 합치기
├── .env.example
├── .env                  ← 직접 만들 개인 설정, 커밋 제외
├── server.py
├── engine.py
├── models.py
├── prompts.py
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── tests/
├── docs/
└── README.md
```

`.git` 폴더는 복사하거나 지우지 않습니다. 기존 README, requirements, tests, .gitignore 또는 같은 이름의 코드 파일이 있으면 내용을 비교해 병합합니다. Git 저장소 루트에 한 번 더 `ai-repo/` 폴더를 중첩하지 않는 구성을 기준으로 안내합니다.

이전에 전체 예제의 `static/`을 복사해 두었다면 해당 화면 코드는 FE 담당자에게 이관합니다. 새 AI 패키지에는 static/이 없고, server.py도 이를 제공하지 않습니다. 기존 코드 삭제는 팀 작업 내용을 확인한 뒤 별도 변경으로 진행하세요.

## 3. Python 가상환경 만들기

macOS/Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Windows 예제는 가상환경 Python을 직접 실행하므로 PowerShell 실행 정책을 바꿀 필요가 없습니다. `.env`가 이미 있으면 복사로 덮어쓰지 말고 부족한 설정만 추가합니다.

VS Code에 Microsoft의 Python 확장을 설치한 뒤 명령 팔레트에서 `Python: Select Interpreter`를 실행하여 이 폴더의 `.venv`를 선택합니다. macOS는 `Command + Shift + P`, Windows는 `Ctrl + Shift + P`로 명령 팔레트를 엽니다.

## 4. 우선 키 없이 연결 시험

`.env`를 다음과 같이 설정합니다.

```dotenv
OPENAI_API_KEY=
AI_MODE=mock
TEXT_MODEL=gpt-4.1-mini
IMAGE_MODEL=gpt-image-1.5
PORT=8002
```

macOS/Linux:

```sh
python server.py
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe server.py
```

실행한 터미널은 열어 둡니다. 브라우저에서 http://127.0.0.1:8002/docs 를 엽니다. 첫 화면의 `/`가 아니라 `/docs`로 들어가야 합니다.

1. `POST /api/chat`을 펼치고 `Try it out`을 누릅니다.
2. 요청에 `{"messages":[]}`를 입력하고 `Execute`를 누릅니다.
3. 응답 코드 200, `question: "오늘은 무슨 일이 있었어?"`가 나오면 성공입니다.
4. 다시 아래 입력으로 실행하면 체험용 후속 질문이 반환됩니다.

```json
{
  "messages": [
    {"role":"assistant","text":"오늘은 무슨 일이 있었어?"},
    {"role":"child","text":"친구와 공놀이를 했어."}
  ]
}
```

동일한 요청을 `POST /api/diary`에서 실행하면 원문 기반 일기와 pages가 반환됩니다. `mock`에서는 그림을 생성하지 않습니다.

## 5. 실제 AI 연결

`.env`의 `OPENAI_API_KEY`에 본인 프로젝트의 API 키를 넣고 `AI_MODE=openai`로 바꿉니다. 키는 코드, 문서, 스크린샷, GitHub에 넣지 않습니다.

터미널에서 `Ctrl + C`로 서버를 종료한 뒤 같은 실행 명령으로 다시 시작합니다. 설정 파일을 고치는 것만으로 실행 중 서버가 자동 변경되지는 않습니다.

다시 `/docs`에서 아이 발언이 포함된 `/api/chat` 요청을 실행합니다. 첫 질문은 고정 문장이므로 첫 질문이 성공했다고 실제 API 키가 정상이라는 뜻은 아닙니다. `/api/status`의 `configured`도 키 문자열 존재 여부만 확인합니다.

## 6. 검사하고 GitHub에 올리기

새 터미널을 열고, macOS/Linux는 가상환경을 활성화한 뒤 실행합니다.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

VS Code 왼쪽 `소스 제어(Source Control)`에서 변경 파일을 확인합니다. `.env`와 `.venv`가 변경 목록에 올라와 있으면 먼저 해결하세요. `.env.example`은 비어 있는 공유 양식이므로 올려도 됩니다.

```sh
git check-ignore .env
git ls-files .env
```

첫 명령은 `.env`를 출력해야 하고, 두 번째는 아무것도 출력하지 않아야 합니다. 이미 .env가 추적 중이라면 `.gitignore`만으로 추적이 해제되지 않습니다. 추적 해제 후 확인하고, 실제 키를 원격 저장소에 올린 적이 있다면 해당 키를 폐기·재발급합니다.

파일별 변경 내용을 확인하고 올릴 파일만 `+`로 스테이징합니다. 커밋 메시지 예: `feat: add AI diary conversation API`. `Commit` 후 새 브랜치라면 `Publish Branch`, 이미 원격 브랜치가 있으면 `Push`를 선택합니다. 이때 개인 설정 파일이 포함되지 않았는지 확인합니다.

터미널로 진행할 경우에도 아래 목록 중 새로 추가/변경한 파일만 검토해 스테이징합니다.

```sh
git add server.py engine.py models.py prompts.py requirements.txt requirements-dev.txt pytest.ini tests docs README.md .gitignore .env.example
git diff --cached --stat
git diff --cached
git commit -m "feat: add AI diary conversation API"
git push -u origin feature/ai-diary-api
```

GitHub에서 해당 브랜치의 변경 내용을 확인하고 팀의 절차에 따라 PR을 만듭니다. 기존 main에 강제로 push하지 않습니다. 이 안내는 사용자가 자신의 저장소에 적용하는 순서이며, 제공 파일을 만든 것만으로 원격 저장소가 변경되지는 않습니다.

## 7. BE 담당자와 연결하기

BE 담당자에게 `docs/API_CONTRACT.md`를 전달합니다. 같은 PC에서 실행할 때 BE 설정에 `AI_SERVICE_URL=http://127.0.0.1:8002`를 두고, BE가 해당 주소로 요청하면 됩니다. 이 변수는 **BE에 추가할 설정 이름**이며 AI 서버의 설정 항목이 아닙니다.

팀원의 다른 PC에서 127.0.0.1은 그 팀원 자신의 PC입니다. 다른 PC나 컨테이너끼리 연결하려면 팀의 내부 주소와 실행 환경 설정이 별도로 필요합니다. 로컬 코드만 실행했다고 인터넷에서 접근 가능한 것은 아닙니다. 공개 포트 노출 대신 BE가 접근할 수 있는 내부 배포 구성을 사용하세요.

공식 참고: [VS Code 소스 제어 안내](https://code.visualstudio.com/docs/sourcecontrol/overview), [저장소·원격 연결 안내](https://code.visualstudio.com/docs/sourcecontrol/repos-remotes).
