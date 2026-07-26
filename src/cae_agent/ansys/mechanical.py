"""Workbench 시스템의 Mechanical 서버 연결과 스크립트 실행을 관리한다.

PyMechanical은 실제 기능 호출 시점에만 지연 import한다. 사용자가 제공한 Python
파일은 외부 CPython에서 실행하지 않고, 원본을 작업공간에 보존한 뒤 파일 내용을
Mechanical의 내장 Python 환경으로 전달한다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from cae_agent.core.config import AppConfig, prepare_workspace
from cae_agent.ansys.workbench import connect_session


class MechanicalError(RuntimeError):
    """Mechanical 세션 또는 실행 결과를 안전하게 처리할 수 없을 때의 오류."""


@dataclass(frozen=True, slots=True)
class MechanicalSession:
    """실행 중인 로컬 Mechanical 서버에 재연결하기 위한 최소 정보."""

    host: str
    port: int
    system_name: str


@dataclass(frozen=True, slots=True)
class MechanicalResult:
    """Mechanical 내부에서 실행한 사용자 스크립트의 반환 결과."""

    run_id: str
    status: str
    system_name: str
    staged_script: str
    return_value: str

    def to_json(self) -> str:
        """CLI와 자동화 도구에서 사용할 JSON 문자열을 반환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _import_mechanical_connector() -> Callable[..., Any]:
    """PyMechanical 연결 함수를 지연 import하고 설치 방법을 안내한다."""
    try:
        from ansys.mechanical.core import connect_to_mechanical
    except ImportError as error:
        raise MechanicalError(
            "PyMechanical이 설치되지 않았습니다. "
            '`python -m pip install -e ".[ansys]"`를 실행하세요.'
        ) from error
    return connect_to_mechanical


def _system_key(system_name: str) -> str:
    """시스템 이름을 경로에 안전한 고정 길이 식별자로 변환한다."""
    return hashlib.sha256(system_name.encode("utf-8")).hexdigest()[:16]


def mechanical_session_file(config: AppConfig, system_name: str) -> Path:
    """요청한 Workbench 시스템의 Mechanical 세션 파일 경로를 계산한다."""
    return (
        config.workspace.root
        / ".runtime"
        / "mechanical"
        / f"{_system_key(system_name)}.json"
    )


def save_mechanical_session(path: Path, session: MechanicalSession) -> None:
    """세션 메타데이터를 임시 파일에 기록한 뒤 원자적으로 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(session), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_mechanical_session(
    path: Path,
    *,
    expected_system_name: str,
) -> MechanicalSession:
    """세션 파일의 필드, localhost, 포트와 시스템 이름을 검증한다."""
    if not path.is_file():
        raise MechanicalError(
            "Mechanical 세션 정보를 찾지 못했습니다. "
            "`cae-agent mechanical connect`를 먼저 실행하세요."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        session = MechanicalSession(
            host=str(data["host"]),
            port=int(data["port"]),
            system_name=str(data["system_name"]),
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise MechanicalError(
            f"Mechanical 세션 파일이 손상되었습니다: {path}"
        ) from error

    if session.host not in {"127.0.0.1", "localhost"}:
        raise MechanicalError("Mechanical 세션은 localhost만 허용합니다.")
    if not 1 <= session.port <= 65535:
        raise MechanicalError("Mechanical 세션 포트가 유효하지 않습니다.")
    if session.system_name != expected_system_name:
        raise MechanicalError(
            "저장된 Mechanical 세션의 Workbench 시스템 이름이 다릅니다."
        )
    return session


def connect_mechanical(
    config: AppConfig,
    *,
    system_name: str,
    connector: Callable[..., Any] | None = None,
) -> Any:
    """검증된 세션 메타데이터로 로컬 Mechanical 서버에 재연결한다."""
    session = load_mechanical_session(
        mechanical_session_file(config, system_name),
        expected_system_name=system_name,
    )
    active_connector = connector or _import_mechanical_connector()
    return active_connector(
        ip=session.host,
        port=session.port,
        cleanup_on_exit=False,
    )


def mechanical_status(mechanical: Any) -> str:
    """Geometry와 Analysis 개수를 읽어 Mechanical 연결 상태를 확인한다."""
    script = """
import json
json.dumps({
    "status": "ok",
    "geometry_count": Model.Geometry.Children.Count,
    "analysis_count": Model.Analyses.Count
})
""".strip()
    return str(mechanical.run_python_script(script))


def start_mechanical_session(
    config: AppConfig,
    *,
    system_name: str,
    workbench: Any | None = None,
    connector: Callable[..., Any] | None = None,
) -> tuple[MechanicalSession, str]:
    """Workbench에서 Mechanical 서버를 시작하고 재연결 정보를 저장한다."""
    if not system_name.strip():
        raise MechanicalError("Workbench 시스템 이름은 비어 있을 수 없습니다.")
    prepare_workspace(config.workspace)
    active_workbench = workbench or connect_session(config)
    try:
        port = int(
            active_workbench.start_mechanical_server(
                system_name=system_name,
            )
        )
    except Exception as error:
        raise MechanicalError(
            f"Mechanical 서버를 시작하지 못했습니다: {error}"
        ) from error
    if not 1 <= port <= 65535:
        raise MechanicalError(
            f"Mechanical 서버가 잘못된 포트를 반환했습니다: {port}"
        )

    active_connector = connector or _import_mechanical_connector()
    try:
        mechanical = active_connector(
            ip="127.0.0.1",
            port=port,
            cleanup_on_exit=False,
        )
        status = mechanical_status(mechanical)
    except Exception as error:
        raise MechanicalError(
            f"Mechanical 서버 연결 확인에 실패했습니다: {error}"
        ) from error

    session = MechanicalSession(
        host="127.0.0.1",
        port=port,
        system_name=system_name,
    )
    save_mechanical_session(
        mechanical_session_file(config, system_name),
        session,
    )
    return session, status


def stage_mechanical_script(
    config: AppConfig,
    script_file: Path,
    *,
    run_id: str,
) -> Path:
    """원본 Mechanical 스크립트를 작업공간에 고유 이름으로 보존한다."""
    source = script_file.expanduser().resolve()
    if not source.is_file():
        raise MechanicalError(
            f"Mechanical 스크립트를 찾을 수 없습니다: {source}"
        )
    if source.suffix.lower() != ".py":
        raise MechanicalError("Mechanical 스크립트는 .py 파일이어야 합니다.")
    prepare_workspace(config.workspace)
    destination = (
        config.workspace.generated_dir / f"mechanical_{run_id}.py"
    )
    shutil.copy2(source, destination)
    return destination


def run_mechanical_script(
    config: AppConfig,
    script_file: Path,
    *,
    system_name: str,
    run_id_factory: Callable[[], str] | None = None,
    mechanical: Any | None = None,
) -> MechanicalResult:
    """보존된 스크립트 내용을 Mechanical 내부 Python에서 실행한다."""
    if not system_name.strip():
        raise MechanicalError("Workbench 시스템 이름은 비어 있을 수 없습니다.")
    create_run_id = run_id_factory or (lambda: uuid.uuid4().hex)
    run_id = create_run_id()
    staged = stage_mechanical_script(config, script_file, run_id=run_id)
    source = staged.read_text(encoding="utf-8")
    active_mechanical = mechanical or connect_mechanical(
        config,
        system_name=system_name,
    )
    try:
        return_value = active_mechanical.run_python_script(source)
    except Exception as error:
        raise MechanicalError(
            f"Mechanical 스크립트 실행이 실패했습니다: {error}"
        ) from error
    return MechanicalResult(
        run_id=run_id,
        status="success",
        system_name=system_name,
        staged_script=str(staged),
        return_value=str(return_value),
    )
