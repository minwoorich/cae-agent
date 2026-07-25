# CAE Agent 문제 해결 가이드

문제를 조사할 때는 먼저 다음 명령을 실행합니다.

```powershell
.\.venv\Scripts\cae-agent.exe doctor
.\.venv\Scripts\cae-agent.exe doctor --json
.\.venv\Scripts\cae-agent.exe config show --json
```

공개 Issue에 결과를 올리기 전 사용자 이름, 로컬 절대경로, 토큰, API 키,
라이선스 서버와 회사 내부 경로를 반드시 제거하세요.

## Python을 찾지 못함

증상:

- `Python 3.11 이상을 찾지 못했습니다.`
- `Python 3.11 이상이 필요합니다.`

확인:

```powershell
py -0p
python --version
```

Python 3.11 이상을 설치하고 새 PowerShell을 연 뒤 `setup.ps1`을 다시 실행합니다.
Microsoft Store 별칭이 실제 설치를 가리는 경우 `-PythonExecutable`에 실제
`python.exe` 경로를 지정합니다. CAE Agent가 시스템 Python을 자동 설치하지는
않습니다.

## Codex CLI를 찾지 못함

증상:

- `doctor`의 Codex 항목이 `WARN`
- `Codex CLI를 찾지 못했습니다.`

확인:

```powershell
Get-Command codex
codex --version
```

[OpenAI 공식 Codex CLI 문서](https://developers.openai.com/codex/cli)의 최신
Windows 설치 절차를 따릅니다. 설치 후 새 PowerShell에서 `codex`를 실행하고
ChatGPT 로그인 또는 계정에 제공되는 로그인 방식을 완료합니다. 토큰을
`cae-agent.toml`이나 Issue에 입력하지 마세요.

## Codex 모델 또는 CLI 버전 불일치

증상:

- `requires a newer version of Codex`
- 지정한 모델이 현재 로그인 방식에서 지원되지 않는다는 오류

해결 순서:

1. `codex --version`을 기록합니다.
2. 공식 설치 방법으로 Codex CLI를 업데이트합니다.
3. `[agent].model`을 제거해 Codex 기본 모델로 다시 시도합니다.
4. 조직에서 모델을 고정해야 한다면
   [공식 구성 문서](https://developers.openai.com/codex/configuration)를 확인하고
   계정에서 실제 지원되는 모델만 지정합니다.

다른 계정에서 보았던 모델 이름을 임의로 복사하면 로그인 방식과 조직 정책 때문에
실패할 수 있습니다.

## Ansys 설치 경로를 찾지 못함

증상:

- `doctor`의 Ansys 항목이 `FAIL`

확인:

```powershell
Get-ChildItem Env:AWP_ROOT*
Get-ChildItem "C:\Program Files\ANSYS Inc" -Directory
```

지원 기준은 Ansys 2026 R1의 내부 버전 V261입니다. 표준 경로가 아니라면 Ansys가
설정한 `AWP_ROOT###` 환경변수를 새 PowerShell이 상속했는지 확인합니다.
CAE Agent는 Ansys나 라이선스를 자동 설치하지 않습니다.

## Workbench 연결 실패

증상:

- 세션 파일이 없거나 손상됐다는 오류
- localhost 포트 연결 실패
- 이전 세션이 응답하지 않음

해결 순서:

```powershell
.\.venv\Scripts\cae-agent.exe workbench status
.\.venv\Scripts\cae-agent.exe workbench stop
.\.venv\Scripts\cae-agent.exe workbench start
```

`start`는 포그라운드 프로세스이므로 해당 PowerShell을 닫지 마세요. 같은
`cae-agent.toml`을 사용하고 있는지, `workbench_port`가 다른 프로그램과 충돌하지
않는지 확인합니다. 방화벽 예외를 만들기 전에 연결 대상이 `127.0.0.1` 또는
`localhost`인지 확인하세요.

## Mechanical 세션 누락

증상:

- `mechanical connect를 먼저 실행하세요.`
- 시스템 이름 불일치

해결:

```powershell
.\.venv\Scripts\cae-agent.exe mechanical `
  --system-name SYS connect
.\.venv\Scripts\cae-agent.exe mechanical `
  --system-name SYS status
```

프로젝트 생성 결과의 실제 시스템 이름을 사용합니다. Workbench를 재시작했다면
Mechanical도 다시 연결해야 합니다.

## SpaceClaim 스크립트 오류

오류 파일은 `workspace/logs`에, 실행 사본과 래퍼는 `workspace/generated`에
보존됩니다. V261에서 자주 확인한 호환 규칙은 다음과 같습니다.

- 길이는 `MM(value)`로 변환합니다.
- 직육면체 결과 바디는 `result.CreatedBodies[0]`으로 가져옵니다.
- 바디 이름은 `body.SetName()`이 아니라 `body.Name = "이름"`으로 지정합니다.
- 한국어 주석이 있는 Python 2 계열 내부 스크립트에는 UTF-8 선언이 필요합니다.

`run-agent`는 오류를 자동 수정할 수 있지만 성공을 보장하지 않습니다. 최대
재시도에 도달하면 마지막 오류와 모든 수정본을 검토하세요.

## 라이선스 오류

CAE Agent가 Ansys 설치 폴더를 찾았더라도 Workbench, SpaceClaim 또는 Mechanical
라이선스가 없으면 실행은 실패할 수 있습니다.

- 다른 Ansys 프로세스가 라이선스를 점유하는지 확인합니다.
- 조직의 Ansys 라이선스 관리자 또는 라이선스 서버 상태를 확인합니다.
- 라이선스 서버 주소와 라이선스 파일은 공개 Issue에 올리지 않습니다.

CAE Agent는 `doctor`에서 라이선스를 체크아웃하지 않으며 라이선스 설정을
자동으로 변경하지 않습니다.

## 한국어 출력이 깨짐

Windows 비대화식 환경에서는 다음 값을 설정한 뒤 다시 실행합니다.

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
```

`setup.ps1`과 GitHub Actions에는 이 처리가 포함돼 있습니다. 외부 터미널의 글꼴과
코드페이지도 UTF-8을 지원하는지 확인합니다.

## 프로젝트를 덮어쓸 수 없음

기존 `.wbpj` 또는 연결된 `_files` 폴더가 있으면 기본 동작으로 중단합니다.
기존 데이터를 보존해야 한다면 다른 출력 이름을 사용하세요. `--overwrite`는
대상 프로젝트를 교체해도 되는 경우에만 명시적으로 사용합니다.

## Issue에 포함할 정보

- CAE Agent 버전: `cae-agent --version`
- Python 버전: `python --version`
- Codex CLI 버전: `codex --version`
- Ansys 내부 버전 번호
- 실패한 명령에서 토큰과 절대경로를 제거한 형태
- `doctor --json`에서 사용자 경로와 내부 경로를 제거한 결과
- `workspace/logs`의 관련 traceback에서 민감정보를 제거한 부분
- 재현에 필요한 최소 입력과 기대 결과

포함하면 안 되는 정보:

- GitHub Personal Access Token, OpenAI API 키 또는 로그인 토큰
- 사용자 홈 전체 경로와 회사 내부 공유 폴더
- Ansys 라이선스 서버 주소와 라이선스 파일
- 비공개 CAD, Workbench 프로젝트 또는 고객 데이터

비밀정보를 이미 공개했다면 Issue만 수정하는 것으로 끝내지 말고 해당 토큰을 즉시
폐기·재발급하세요.
