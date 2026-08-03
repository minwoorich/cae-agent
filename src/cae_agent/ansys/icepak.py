"""PyAEDT를 통해 Ansys Icepak 프로젝트와 AI 생성 스크립트를 제어한다.

PyAEDT는 선택 의존성이다. 모듈 import만으로 AEDT를 요구하지 않고 실제 연결
시점에만 지연 import하여, Ansys가 없는 환경에서도 기본 테스트가 동작하게 한다.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from cae_agent.core.config import AppConfig, prepare_workspace


class IcepakError(RuntimeError):
    """Icepak 연결, 프로젝트 검증 또는 스크립트 실행 실패를 나타낸다."""


@dataclass(frozen=True, slots=True)
class IcepakResult:
    """Icepak 내부에서 실행한 스크립트와 반환값을 기록한다."""

    run_id: str
    status: str
    project: str
    design: str
    staged_script: str
    return_value: str

    def to_json(self) -> str:
        """자동화 도구가 소비할 수 있는 JSON 문자열을 반환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def pyaedt_version(ansys_version: str) -> str:
    """CAE Agent의 ``261`` 형식을 PyAEDT의 ``2026.1`` 형식으로 변환한다."""
    value = ansys_version.strip()
    if len(value) == 3 and value.isdigit():
        return f"20{value[:2]}.{value[2]}"
    return value


def _import_icepak_factory() -> Callable[..., Any]:
    """Icepak 클래스를 지연 import하고 설치 방법이 포함된 오류를 제공한다."""
    try:
        from ansys.aedt.core import Icepak
    except ImportError as error:
        raise IcepakError(
            "PyAEDT가 설치되지 않았습니다. "
            '`python -m pip install -e ".[icepak]"`을 실행하세요.'
        ) from error
    return Icepak


def _resolve_project(project_file: Path) -> Path:
    """기존 AEDT 프로젝트만 연결하도록 입력 경로와 확장자를 검증한다."""
    project = project_file.expanduser().resolve()
    if not project.is_file():
        raise IcepakError(f"Icepak 프로젝트를 찾을 수 없습니다: {project}")
    if project.suffix.lower() not in {".aedt", ".aedtz"}:
        raise IcepakError("Icepak 프로젝트는 .aedt 또는 .aedtz 파일이어야 합니다.")
    return project


def connect_icepak(
    config: AppConfig,
    *,
    project_file: Path,
    design_name: str | None = None,
    new_desktop: bool = False,
    student_version: bool = False,
    aedt_version: str | None = None,
    factory: Callable[..., Any] | None = None,
) -> Any:
    """기존 Icepak 프로젝트를 열고 PyAEDT 애플리케이션 객체를 반환한다."""
    project = _resolve_project(project_file)
    active_factory = factory or _import_icepak_factory()
    try:
        return active_factory(
            project=str(project),
            design=design_name,
            version=aedt_version or pyaedt_version(config.ansys.version),
            non_graphical=config.ansys.headless,
            new_desktop=new_desktop,
            close_on_exit=False,
            student_version=student_version,
        )
    except Exception as error:
        raise IcepakError(f"Icepak 프로젝트 연결에 실패했습니다: {error}") from error


def icepak_status(app: Any) -> str:
    """활성 프로젝트와 설계 이름을 읽어 연결 상태를 JSON으로 반환한다."""
    try:
        payload = {
            "status": "ok",
            "project": str(app.project_name),
            "design": str(app.design_name),
            "solution_type": str(getattr(app, "solution_type", "")),
        }
    except Exception as error:
        raise IcepakError(f"Icepak 상태 확인에 실패했습니다: {error}") from error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def stage_icepak_script(
    config: AppConfig,
    script_file: Path,
    *,
    run_id: str,
) -> Path:
    """원본을 보존하고 실행 사본을 generated/icepak 아래에 저장한다."""
    source = script_file.expanduser().resolve()
    if not source.is_file():
        raise IcepakError(f"Icepak 스크립트를 찾을 수 없습니다: {source}")
    if source.suffix.lower() != ".py":
        raise IcepakError("Icepak 스크립트는 .py 파일이어야 합니다.")
    prepare_workspace(config.workspace)
    output_dir = config.workspace.generated_dir / "icepak"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"icepak_{run_id}.py"
    shutil.copy2(source, destination)
    return destination


def run_icepak_script(
    config: AppConfig,
    script_file: Path,
    *,
    project_file: Path,
    design_name: str | None = None,
    new_desktop: bool = False,
    student_version: bool = False,
    aedt_version: str | None = None,
    app: Any | None = None,
    factory: Callable[..., Any] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> IcepakResult:
    """검증된 사본을 ``icepak``과 ``app`` 객체가 주입된 환경에서 실행한다."""
    run_id = (run_id_factory or (lambda: uuid.uuid4().hex))()
    staged = stage_icepak_script(config, script_file, run_id=run_id)
    source = staged.read_text(encoding="utf-8")
    active_app = app or connect_icepak(
        config,
        project_file=project_file,
        design_name=design_name,
        new_desktop=new_desktop,
        student_version=student_version,
        aedt_version=aedt_version,
        factory=factory,
    )
    namespace: dict[str, Any] = {
        "__name__": "__cae_agent_icepak__",
        "icepak": active_app,
        "app": active_app,
    }
    try:
        exec(compile(source, str(staged), "exec"), namespace)
    except Exception as error:
        raise IcepakError(f"Icepak 스크립트 실행에 실패했습니다: {error}") from error
    return IcepakResult(
        run_id=run_id,
        status="success",
        project=str(getattr(active_app, "project_name", project_file)),
        design=str(getattr(active_app, "design_name", design_name or "")),
        staged_script=str(staged),
        return_value=str(namespace.get("result", "")),
    )
