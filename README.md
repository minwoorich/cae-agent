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
