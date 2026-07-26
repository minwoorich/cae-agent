# CAE Agent

[![Windows CI](https://github.com/minwoorich/cae-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/minwoorich/cae-agent/actions/workflows/ci.yml)

CAE Agent is an open-source command-line tool for AI-assisted automation of
Ansys SpaceClaim and Mechanical.

The project is in its initial development stage. The first supported platform
will be Windows with Ansys 2026 R1, using Codex CLI as the first AI agent
provider.

## Documentation

- [Codex 자연어 인터페이스 가이드](docs/codex-first.ko.md)
- [로컬 상태·승인 대시보드](docs/ui.ko.md)
- [UI 정보 구조와 디자인 시스템](docs/ui-design.ko.md)
- [한국어 시작 가이드](docs/getting-started.ko.md)
- [한국어 문제 해결 가이드](docs/troubleshooting.ko.md)
- [전력반도체 열해석 공식 예제](examples/power-semiconductor-thermal/README.md)
- [변경 이력](CHANGELOG.md)
- [v0.1.0 릴리스 노트 초안](docs/releases/v0.1.0.ko.md)
- [OpenAI 공식 Codex CLI 문서](https://developers.openai.com/codex/cli)

## Codex-first quick start

CAE Agent is designed so that Codex can be the user interface and the CLI can
remain an internal execution tool. Open the cloned repository in Codex and
start with a natural-language request:

> 이 저장소의 CAE Agent를 처음 사용하는 사용자처럼 준비해줘. 기존 파일은
> 덮어쓰지 말고 설치 계획을 먼저 설명해줘. 준비가 끝나면 doctor를 실행하고
> Python, Codex와 Ansys 상태를 한국어로 요약해줘.

The repository-local `AGENTS.md` and CAE Agent Skill teach Codex how to select
commands, preserve user data, and request approval before risky Ansys changes.
See the [Codex-first Korean guide](docs/codex-first.ko.md) for complete
conversation examples. Direct PowerShell commands below remain available for
manual operation and debugging.

Codex can also report accumulated workspace usage and preview retention-based
cleanup without deleting files. Actual cleanup requires a separate explicit
approval, never includes `workspace/input` or `workspace/results`, and is
blocked while session metadata is present.

For an optional local dashboard, install the UI extra and start the
localhost-only NiceGUI server:

```powershell
.\setup.ps1 -WithAnsys -WithUI
.\.venv\Scripts\cae-agent.exe ui
```

The dashboard can store validated CAE input files in `workspace/input`
without overwriting existing files or automatically starting Ansys.
Its current chat screen is an explicit mock for testing streaming, stop,
retry, and attachment UX; it does not run Codex or Ansys yet.

The dashboard displays diagnostics, session metadata, workspace usage, recent
file names, and cleanup approval. It does not expose model-editing controls or
listen on an external network interface.

## Development setup

Python 3.11 or newer is required.

For the recommended Windows setup with Ansys integration:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1 -WithAnsys
```

The script creates or reuses the repository-local `.venv`, installs CAE Agent,
copies `cae-agent.example.toml` only when `cae-agent.toml` is missing, and runs
`doctor`. It never installs Python, Codex CLI, or Ansys system-wide and never
requests credentials. Preview every planned action without changing files:

```powershell
.\setup.ps1 -WithAnsys -WithDev -WhatIf
```

If Python is missing, install Python 3.11 or newer first. If Codex is missing,
the core and Ansys integration can still be installed, but AI generation is
unavailable until Codex is installed and logged in. If Ansys is missing,
`doctor` returns a failure after setup and explains the expected installation
locations; Ansys and its license must be installed separately.

Manual development setup:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the CLI:

```powershell
.\.venv\Scripts\cae-agent.exe --help
.\.venv\Scripts\cae-agent.exe --version
```

Diagnose the local environment:

```powershell
.\.venv\Scripts\cae-agent.exe doctor
.\.venv\Scripts\cae-agent.exe doctor --json
```

`doctor` checks the supported operating system, Python, virtual environment,
Git, GitHub CLI, Codex CLI, Ansys installation paths, and workspace write
access. It does not launch Ansys or request an Ansys license.

Inspect the validated configuration and prepare its workspace:

```powershell
Copy-Item .\cae-agent.example.toml .\cae-agent.toml
.\.venv\Scripts\cae-agent.exe config show
.\.venv\Scripts\cae-agent.exe config show --json --prepare
```

Relative workspace paths are resolved from the configuration file directory.
Credentials and API tokens must not be stored in this TOML file.

Install the optional PyWorkbench integration:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ansys]"
```

Start and control a persistent Workbench bridge:

```powershell
# Keep this terminal open while the Workbench session is in use.
.\.venv\Scripts\cae-agent.exe workbench start

# Run these commands from another terminal.
.\.venv\Scripts\cae-agent.exe workbench status
.\.venv\Scripts\cae-agent.exe workbench run-script .\example.wbjn
.\.venv\Scripts\cae-agent.exe workbench stop
```

Create a new Steady-State Thermal project inside the workspace:

```powershell
.\.venv\Scripts\cae-agent.exe workbench create-project `
  --output .\results\power-semiconductor.wbpj
```

Existing `.wbpj` files and their companion `_files` directories are protected
unless `--overwrite` is explicitly provided. Project output paths outside the
configured workspace are rejected.

Workbench session metadata stays inside the configured workspace. Only local
loopback connections are accepted, and no authentication token is written to
the session file.

Run a SpaceClaim Python script in an existing Workbench system:

```powershell
.\.venv\Scripts\cae-agent.exe spaceclaim run .\geometry.py `
  --system-name "SYS"
```

Use `--clear` only when the existing geometry should be removed before running
the script. The original input is never modified; a uniquely named copy is
preserved in the configured `workspace/generated` directory.

Connect to Mechanical and run an internal Python script:

```powershell
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" connect
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" status
.\.venv\Scripts\cae-agent.exe mechanical --system-name "SYS" `
  run-script .\mechanical_setup.py
```

Mechanical connection metadata is stored per Workbench system. Only localhost
connections are accepted, and the original script is preserved unchanged.

Generate a CAE script with the locally authenticated Codex CLI:

```powershell
.\.venv\Scripts\cae-agent.exe generate `
  --target spaceclaim `
  --prompt "가로 60 mm, 세로 40 mm, 높이 3 mm인 독립 바디를 생성해줘"
```

Codex runs non-interactively with a read-only sandbox and an ephemeral session.
The structured response is validated before the script and metadata are saved
under `workspace/generated`. Generated code is never executed automatically.
If the configured default model requires a newer Codex CLI, update Codex or
optionally set `model = "a-model-supported-by-your-cli"` in `[agent]`.

Generate, execute, and repair a script in an already prepared Ansys session:

```powershell
.\.venv\Scripts\cae-agent.exe run-agent `
  --target mechanical `
  --system-name SYS `
  --prompt "최대 온도 결과를 추가하고 해석해줘" `
  --approve-execution
```

`run-agent` refuses to execute generated code unless `--approve-execution` is
present. On failure it preserves the script and error, asks Codex for a
targeted correction, and retries no more than `[agent].max_retries`. Review
the JSON history under `workspace/logs`; the command expects the Workbench and
Mechanical sessions to have been prepared separately.

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Project status

Version 0.1.0 is the first public alpha release candidate. Release scope and
remaining publication work are tracked in
[GitHub issue #1](https://github.com/minwoorich/cae-agent/issues/1) and
[release issue #30](https://github.com/minwoorich/cae-agent/issues/30).

## Development conventions

- 코드의 식별자와 공개 CLI 옵션은 일반적인 Python 관례에 따라 영어를
  사용합니다.
- 주석과 docstring은 구현 의도, 제약조건, 오류 처리 방식을 이해할 수 있도록
  자세한 한국어로 작성합니다.
- 단순히 코드를 다시 읽어주는 주석은 피하고, Ansys 버전 차이나 외부 프로세스
  제어처럼 코드만으로 알기 어려운 배경을 우선 기록합니다.
