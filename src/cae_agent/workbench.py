"""로컬 Ansys Workbench 세션의 실행, 재연결 및 종료를 관리한다.

PyWorkbench는 Ansys 자동화를 사용할 때만 필요한 선택 의존성이다. 모듈 최상위에서
가져오지 않고 실제 Workbench 명령을 실행하는 시점에만 불러오므로, Ansys가 없는
사용자도 CAE Agent의 설치, 설정 확인 및 환경 진단 기능을 사용할 수 있다.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from cae_agent.config import AppConfig, prepare_workspace


class WorkbenchError(RuntimeError):
    """Workbench 세션을 안전하게 처리할 수 없을 때 발생하는 오류."""


@dataclass(frozen=True, slots=True)
class WorkbenchPaths:
    """하나의 작업공간에 격리된 Workbench 런타임 경로."""

    runtime: Path
    client: Path
    server: Path
    session_file: Path
    stop_file: Path


@dataclass(frozen=True, slots=True)
class WorkbenchSession:
    """실행 중인 로컬 Workbench 브리지에 재연결하기 위한 최소 정보."""

    host: str
    port: int
    security: str
    server_version: str
    bridge_pid: int


def workbench_paths(config: AppConfig) -> WorkbenchPaths:
    """설정된 작업공간 아래에서 Workbench 전용 경로를 계산한다."""
    runtime = config.workspace.root / ".runtime" / "workbench"
    return WorkbenchPaths(
        runtime=runtime,
        client=runtime / "client",
        server=runtime / "server",
        session_file=runtime / "session.json",
        stop_file=runtime / "stop.request",
    )


def _import_workbench_api() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """PyWorkbench API를 지연 import하고 설치 방법을 포함해 오류를 설명한다."""
    try:
        from ansys.workbench.core import (
            connect_workbench,
            launch_workbench,
        )
    except ImportError as error:
        raise WorkbenchError(
            "PyWorkbench가 설치되지 않았습니다. "
            '`python -m pip install -e ".[ansys]"`를 실행하세요.'
        ) from error
    return launch_workbench, connect_workbench


def prepare_workbench_paths(config: AppConfig) -> WorkbenchPaths:
    """작업공간과 Workbench 통신 폴더를 생성한다."""
    prepare_workspace(config.workspace)
    paths = workbench_paths(config)
    paths.client.mkdir(parents=True, exist_ok=True)
    paths.server.mkdir(parents=True, exist_ok=True)
    return paths


def save_session(path: Path, session: WorkbenchSession) -> None:
    """세션 정보를 임시 파일에 쓴 뒤 원자적으로 교체한다.

    프로세스가 JSON 기록 도중 종료되어 손상된 세션 파일이 남는 가능성을 줄이기
    위해 동일 폴더의 임시 파일을 완성한 후 최종 경로로 교체한다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(session), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_session(path: Path) -> WorkbenchSession:
    """세션 JSON을 읽고 localhost 연결에 필요한 필드를 엄격히 검증한다."""
    if not path.is_file():
        raise WorkbenchError(
            "실행 중인 Workbench 세션 정보를 찾지 못했습니다. "
            "`cae-agent workbench start`를 먼저 실행하세요."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = WorkbenchSession(
            host=str(data["host"]),
            port=int(data["port"]),
            security=str(data["security"]),
            server_version=str(data["server_version"]),
            bridge_pid=int(data["bridge_pid"]),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise WorkbenchError(
            f"Workbench 세션 파일이 손상되었습니다: {path}"
        ) from error

    # 원격 호스트 주소를 세션 파일에 삽입해 임의 서버로 연결시키는 공격이나
    # 실수를 막기 위해 현재 버전은 로컬 루프백 연결만 허용한다.
    if session.host not in {"127.0.0.1", "localhost"}:
        raise WorkbenchError("Workbench 세션은 localhost만 허용합니다.")
    if not 1 <= session.port <= 65535:
        raise WorkbenchError("Workbench 세션 포트가 유효하지 않습니다.")
    return session


def connect_session(
    config: AppConfig,
    *,
    connector: Callable[..., Any] | None = None,
) -> Any:
    """저장된 세션 정보로 실행 중인 로컬 Workbench에 연결한다."""
    paths = workbench_paths(config)
    session = load_session(paths.session_file)
    if connector is None:
        _, connector = _import_workbench_api()
    return connector(
        host=session.host,
        port=session.port,
        client_workdir=str(paths.client),
        security=session.security,
    )


def ping_session(workbench: Any) -> Any:
    """Workbench 내부에서 현재 프로젝트 경로를 읽어 연결 상태를 확인한다."""
    return workbench.run_script_string(
        "import json\n"
        "wb_script_result = json.dumps({"
        "'status': 'ok', 'project_file': GetProjectFile()"
        "})"
    )


def run_script(config: AppConfig, script_file: Path) -> Any:
    """명시적으로 전달된 로컬 Workbench 저널 파일을 현재 세션에서 실행한다."""
    resolved = script_file.expanduser().resolve()
    if not resolved.is_file():
        raise WorkbenchError(f"실행할 스크립트를 찾을 수 없습니다: {resolved}")
    workbench = connect_session(config)
    return workbench.run_script_file(str(resolved), log_level="info")


def request_stop(config: AppConfig) -> Path:
    """브리지 프로세스가 정상 종료하도록 작업공간 안에 종료 요청을 기록한다."""
    paths = workbench_paths(config)
    if not paths.session_file.is_file():
        raise WorkbenchError("종료할 Workbench 세션이 없습니다.")
    paths.stop_file.touch(exist_ok=True)
    return paths.stop_file


def serve_session(
    config: AppConfig,
    *,
    launcher: Callable[..., Any] | None = None,
    poll_interval: float = 1.0,
) -> None:
    """Workbench를 실행하고 종료 요청이 올 때까지 브리지를 유지한다.

    이 함수는 의도적으로 포그라운드에서 대기한다. 사용자는 이 터미널을 세션
    브리지로 유지하고 다른 터미널에서 status, run-script, stop 명령을 실행한다.
    비정상 종료가 발생해도 세션 메타데이터를 정리하여 오래된 연결 정보가 다음
    실행에 재사용되지 않게 한다.
    """
    paths = prepare_workbench_paths(config)
    if paths.session_file.exists():
        raise WorkbenchError(
            "세션 파일이 이미 존재합니다. 기존 세션 상태를 확인하세요."
        )
    if paths.stop_file.exists():
        paths.stop_file.unlink()

    if launcher is None:
        launcher, _ = _import_workbench_api()

    running = {"value": True}

    def stop_on_signal(_signum: int, _frame: Any) -> None:
        running["value"] = False

    signal.signal(signal.SIGINT, stop_on_signal)
    signal.signal(signal.SIGTERM, stop_on_signal)

    workbench = launcher(
        show_gui=not config.ansys.headless,
        version=config.ansys.version,
        client_workdir=str(paths.client),
        server_workdir=str(paths.server),
        port=config.ansys.workbench_port,
        use_insecure_connection=True,
    )
    session = WorkbenchSession(
        host="127.0.0.1",
        port=config.ansys.workbench_port,
        security="insecure",
        server_version=str(workbench.server_version),
        bridge_pid=os.getpid(),
    )
    save_session(paths.session_file, session)

    try:
        ping_session(workbench)
        while running["value"] and not paths.stop_file.exists():
            time.sleep(poll_interval)
    finally:
        paths.session_file.unlink(missing_ok=True)
        paths.stop_file.unlink(missing_ok=True)
