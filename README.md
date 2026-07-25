# CAE Agent

CAE Agent is an open-source command-line tool for AI-assisted automation of
Ansys SpaceClaim and Mechanical.

The project is in its initial development stage. The first supported platform
will be Windows with Ansys 2026 R1, using Codex CLI as the first AI agent
provider.

## Development setup

Python 3.11 or newer is required.

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

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Project status

The v0.1.0 roadmap is tracked in
[GitHub issue #1](https://github.com/minwoorich/cae-agent/issues/1).

## Development conventions

- 코드의 식별자와 공개 CLI 옵션은 일반적인 Python 관례에 따라 영어를
  사용합니다.
- 주석과 docstring은 구현 의도, 제약조건, 오류 처리 방식을 이해할 수 있도록
  자세한 한국어로 작성합니다.
- 단순히 코드를 다시 읽어주는 주석은 피하고, Ansys 버전 차이나 외부 프로세스
  제어처럼 코드만으로 알기 어려운 배경을 우선 기록합니다.
