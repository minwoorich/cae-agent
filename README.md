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
