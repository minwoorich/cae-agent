# CAE Agent 시작 가이드

이 문서는 Windows와 Ansys 2026 R1(V261)을 기준으로 CAE Agent를 처음 설치하고,
빈 Workbench 프로젝트에서 SpaceClaim 또는 Mechanical 스크립트를 실행하는
과정을 설명합니다.

## 1. 필요한 프로그램

| 구성요소 | 필요한 이유 | 설치되지 않았을 때 |
|---|---|---|
| Python 3.11 이상 | CAE Agent CLI와 연결 모듈 실행 | `setup.ps1`이 중단됩니다. |
| Git | 저장소 다운로드와 버전 관리 | `doctor`가 `FAIL`을 반환합니다. |
| Codex CLI | 자연어로 CAE 스크립트 생성·수정 | 수동 스크립트 실행은 가능하지만 AI 기능은 사용할 수 없습니다. |
| Ansys 2026 R1 | Workbench, SpaceClaim, Mechanical 실행 | 생성 기능은 쓸 수 있지만 CAE 실행은 불가능합니다. |

CAE Agent는 Python, Codex CLI, Ansys 또는 라이선스를 시스템에 자동 설치하지
않습니다. 각 제품의 설치 약관과 조직 정책을 사용자가 직접 확인해야 합니다.

Codex CLI 설치 방법은 변경될 수 있으므로 [OpenAI 공식 Codex CLI 문서][codex-cli]의
Windows 설치 탭을 따르세요. 설치 후 프로젝트 폴더에서 `codex`를 처음 실행하고
`Sign in with ChatGPT` 또는 계정에 제공되는 다른 로그인 방식을 선택합니다.
CAE Agent는 이 로그인 정보를 재사용하며 토큰을 읽거나 설정 파일에 저장하지
않습니다.

[codex-cli]: https://developers.openai.com/codex/cli

## 2. 저장소 설치

PowerShell에서 저장소 루트로 이동한 뒤 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1 -WithAnsys
```

개발용 테스트 도구도 필요하면 `-WithDev`를 함께 지정합니다.

```powershell
.\setup.ps1 -WithAnsys -WithDev
```

실제 파일이나 패키지를 변경하지 않고 계획만 확인할 수도 있습니다.

```powershell
.\setup.ps1 -WithAnsys -WithDev -WhatIf
```

주요 옵션:

| 옵션 | 동작 |
|---|---|
| `-WithAnsys` | PyWorkbench와 PyMechanical 선택 의존성을 설치합니다. |
| `-WithDev` | pytest 같은 개발·테스트 의존성을 설치합니다. |
| `-PythonExecutable PATH` | 자동 탐색 대신 지정한 Python을 사용합니다. |
| `-VirtualEnvironment PATH` | 저장소 내부의 다른 가상환경 경로를 사용합니다. |
| `-SkipPipUpgrade` | 네트워크가 제한된 환경에서 pip 업그레이드를 생략합니다. |
| `-WhatIf` | 변경 없이 설치 계획만 출력합니다. |

스크립트는 기존 가상환경과 `cae-agent.toml`을 삭제하거나 덮어쓰지 않습니다.
마지막 `doctor`에서 `FAIL`이 나오면 기본 패키지 설치가 끝났더라도 해당 필수
구성요소가 아직 준비되지 않은 것입니다.

## 3. 환경 진단과 설정

```powershell
.\.venv\Scripts\cae-agent.exe doctor
.\.venv\Scripts\cae-agent.exe config show --json --prepare
```

`doctor`는 설치 경로만 확인하며 Ansys를 실행하거나 라이선스를 점유하지 않습니다.
설정은 `cae-agent.toml`에 있으며 토큰, API 키 또는 라이선스 정보를 넣으면 안
됩니다.

Codex 모델은 기본적으로 로그인된 Codex CLI의 현재 기본값을 사용합니다. 특정
모델이 꼭 필요한 경우에만 다음처럼 선택적으로 지정합니다.

```toml
[agent]
provider = "codex"
model = "계정과 설치된 Codex CLI가 지원하는 모델"
max_retries = 3
timeout_seconds = 300
```

모델 호환 오류가 발생하면 임의 모델 이름을 추측하기보다 Codex CLI를 먼저
업데이트하고 [OpenAI 공식 Codex 구성 문서][codex-config]에서 현재 계정의 모델
선택 방법을 확인하세요.

[codex-config]: https://developers.openai.com/codex/configuration

## 4. 빈 Workbench 프로젝트 준비

첫 번째 PowerShell에서 Workbench 브리지를 시작하고 이 창을 열어 둡니다.

```powershell
.\.venv\Scripts\cae-agent.exe workbench start
```

두 번째 PowerShell에서 새 정상상태 열해석 프로젝트를 만듭니다.

```powershell
.\.venv\Scripts\cae-agent.exe workbench create-project `
  --output .\results\first-project.wbpj
```

기존 프로젝트는 기본적으로 덮어쓰지 않습니다. `--overwrite`는 대상 프로젝트와
연결 폴더를 교체해도 된다는 사실을 확인한 경우에만 사용하세요.

## 5. 스크립트 생성과 실행 방법 선택

### 검토 후 수동 실행

`generate`는 코드를 만들고 저장만 하며 Ansys에서 실행하지 않습니다.

```powershell
.\.venv\Scripts\cae-agent.exe generate `
  --target spaceclaim `
  --prompt "10 mm x 10 mm x 1 mm 독립 직육면체를 만들어줘"
```

`workspace/generated`의 `.py`와 `.metadata.json`을 검토한 뒤 실행합니다.

```powershell
.\.venv\Scripts\cae-agent.exe spaceclaim run `
  .\workspace\generated\spaceclaim_RUN_ID.py `
  --system-name SYS
```

### 승인 후 제한적 자동 수정

`run-agent`는 생성 코드를 실행하고 실패 traceback을 바탕으로 설정된 횟수만큼
수정합니다. `--approve-execution`을 명시하지 않으면 Codex 호출 전에 중단됩니다.

```powershell
.\.venv\Scripts\cae-agent.exe run-agent `
  --target spaceclaim `
  --system-name SYS `
  --prompt "10 mm x 10 mm x 1 mm 독립 직육면체를 만들어줘" `
  --approve-execution
```

| 명령 | 생성 | 자동 실행 | 오류 기반 수정 |
|---|---:|---:|---:|
| `generate` | 예 | 아니요 | 아니요 |
| `run-agent` | 예 | 승인 필요 | 최대 `max_retries`회 |
| `spaceclaim run` / `mechanical run-script` | 아니요 | 사용자가 지정한 파일만 | 아니요 |

`--clear`는 SpaceClaim의 기존 형상을 모두 제거할 의도가 확실할 때만 사용하세요.

## 6. Mechanical 실행

Workbench 시스템의 Mechanical 서버를 먼저 시작하고 연결합니다.

```powershell
.\.venv\Scripts\cae-agent.exe mechanical `
  --system-name SYS connect
```

수동 스크립트 실행:

```powershell
.\.venv\Scripts\cae-agent.exe mechanical `
  --system-name SYS run-script .\mechanical_setup.py
```

AI 생성·수정 실행:

```powershell
.\.venv\Scripts\cae-agent.exe run-agent `
  --target mechanical `
  --system-name SYS `
  --prompt "최대 온도 결과를 추가해줘" `
  --approve-execution
```

`run-agent`는 프로젝트 생성이나 Mechanical 연결을 대신하지 않습니다. 연결을
먼저 완료해야 합니다.

## 7. 작업공간

| 폴더 | 내용 |
|---|---|
| `workspace/input` | 사용자가 제공하는 원본 입력 |
| `workspace/generated` | AI 생성본과 실행 전 보존 사본 |
| `workspace/logs` | 자동 수정 이력과 traceback |
| `workspace/results` | Workbench 프로젝트와 해석 결과 |
| `workspace/.runtime` | 로컬 세션 정보와 중간 파일 |

`.runtime`에는 비밀 토큰을 저장하지 않지만 로컬 포트와 경로가 포함될 수 있으므로
Issue에 그대로 첨부하지 마세요.

작업공간이 얼마나 커졌는지는 다음 명령으로 확인합니다.

```powershell
.\.venv\Scripts\cae-agent.exe workspace status
```

오래된 생성 스크립트, 로그와 Codex 임시 파일의 정리 후보는 기본 dry-run으로
확인할 수 있습니다. 다음 명령은 어떤 파일도 삭제하지 않습니다.

```powershell
.\.venv\Scripts\cae-agent.exe workspace clean --older-than 30
```

목록과 용량을 확인한 뒤 실제 삭제에 동의하는 경우에만 `--approve`를
추가합니다. `workspace/input`과 `workspace/results`는 보존 기간과 관계없이
자동 정리 대상에서 제외됩니다. 실행 중이거나 종료가 확인되지 않은 Workbench
또는 Mechanical 세션 정보가 있으면 실제 정리가 차단됩니다.

```powershell
.\.venv\Scripts\cae-agent.exe workspace clean `
  --older-than 30 `
  --approve
```

## 8. 종료와 다음 단계

작업을 마치면 Workbench 브리지를 정상 종료합니다.

```powershell
.\.venv\Scripts\cae-agent.exe workbench stop
```

전체 검증 예제가 필요하면
[전력반도체 정상상태 열해석 예제](../examples/power-semiconductor-thermal/README.md)를
따르세요. 문제가 발생하면 [문제 해결 가이드](troubleshooting.ko.md)를 먼저
확인합니다.
