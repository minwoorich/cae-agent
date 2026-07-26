# CAE Agent 명령 참조

명령은 저장소 루트에서 실행한다. Windows에서는
`.\.venv\Scripts\cae-agent.exe`를 우선 사용한다.

## 설치와 진단

```powershell
.\setup.ps1 -WithAnsys
.\.venv\Scripts\cae-agent.exe doctor --json
.\.venv\Scripts\cae-agent.exe config show --prepare
```

`setup.ps1`은 Python, Codex CLI와 Ansys를 시스템에 설치하지 않는다. 기존
가상환경과 `cae-agent.toml`을 보존한다.

## Workbench

```powershell
.\.venv\Scripts\cae-agent.exe workbench status
.\.venv\Scripts\cae-agent.exe workbench start
.\.venv\Scripts\cae-agent.exe workbench create-project `
  --template "Steady-State Thermal" `
  --solver "ANSYS" `
  --output "projects\user_test.wbpj"
.\.venv\Scripts\cae-agent.exe workbench stop
```

`workbench start`는 브리지를 현재 프로세스에서 계속 유지한다. Codex가
호출할 때는 `Start-Process -WindowStyle Hidden`으로 별도 프로세스를 시작하고
`workbench status`가 성공할 때까지 로그를 확인한다. 이미 실행 중인 세션을
중복 시작하지 않는다.

## SpaceClaim

```powershell
.\.venv\Scripts\cae-agent.exe spaceclaim run `
  "workspace\input\geometry.py" `
  --system-name "SYS"
```

기존 형상을 전부 삭제해야 하고 사용자가 승인한 경우에만 `--clear`를 추가한다.

## Mechanical

```powershell
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" connect
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" status
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" `
  run-script "workspace\input\mechanical_setup.py"
```

Mechanical 연결 전에 Workbench 세션과 대상 시스템이 존재해야 한다.

## 내부 Codex 어댑터 시험

최상위 Codex가 조정 중이면 이 명령을 일반 CAE 작업에 중첩 호출하지 않는다.
사용자가 어댑터 자체를 시험한다고 명시한 경우에만 사용한다.

```powershell
.\.venv\Scripts\cae-agent.exe generate `
  --target spaceclaim `
  --prompt "가로 60 mm, 세로 40 mm, 높이 3 mm 바디를 생성해줘"

.\.venv\Scripts\cae-agent.exe run-agent `
  --target spaceclaim `
  --system-name "SYS" `
  --prompt "동일한 바디를 생성해줘" `
  --approve-execution
```

두 번째 명령의 `--approve-execution`은 사용자가 AI 생성 코드 실행을
명시적으로 승인한 경우에만 사용할 수 있다.

## 작업공간 상태와 정리

```powershell
.\.venv\Scripts\cae-agent.exe workspace status
.\.venv\Scripts\cae-agent.exe workspace status --json
.\.venv\Scripts\cae-agent.exe workspace clean --older-than 30
```

세 번째 명령은 기본 dry-run이며 파일을 삭제하지 않는다. 후보 목록과 용량을
사용자에게 설명하고 실제 삭제 승인을 받은 경우에만 다음을 실행한다.

```powershell
.\.venv\Scripts\cae-agent.exe workspace clean `
  --older-than 30 `
  --approve
```

`input`과 `results`는 항상 자동 정리에서 제외된다. 활성 세션 메타데이터가
있으면 실제 정리를 강행하지 말고 Workbench와 Mechanical을 정상 종료한다.

## 로컬 대시보드

```powershell
.\setup.ps1 -WithAnsys -WithUI
.\.venv\Scripts\cae-agent.exe ui
```

다른 로컬 포트에서 브라우저 자동 실행 없이 시작할 수 있다.

```powershell
.\.venv\Scripts\cae-agent.exe ui --port 8876 --no-browser
```

UI는 항상 `127.0.0.1`에 바인딩된다. 외부 주소에 노출하거나 모델 편집과 해석
실행을 UI 버튼으로 우회하지 않는다.

UI에서 업로드한 허용 형식의 파일은 `workspace/input`에 저장된다. 업로드는
기존 파일을 덮어쓰지 않고 Ansys 작업을 자동 실행하지 않는다. 저장 후에는
파일명과 원하는 작업을 Codex에 자연어로 요청한다.
