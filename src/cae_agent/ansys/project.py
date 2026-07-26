"""새 Workbench 해석 시스템과 프로젝트 파일을 안전하게 생성한다."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cae_agent.core.config import AppConfig, prepare_workspace
from cae_agent.ansys.workbench import connect_session


class ProjectError(RuntimeError):
    """Workbench 프로젝트 생성 요청 또는 결과가 유효하지 않을 때의 오류."""


@dataclass(frozen=True, slots=True)
class ProjectResult:
    """새로 생성된 Workbench 시스템과 프로젝트의 검증 결과."""

    status: str
    template_name: str
    solver: str
    system_name: str
    project_file: str

    def to_json(self) -> str:
        """CLI와 자동화 도구가 사용할 JSON 문자열을 반환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def resolve_project_output(
    config: AppConfig,
    output: Path | None,
    *,
    overwrite: bool,
) -> Path:
    """출력 경로를 작업공간 내부로 제한하고 기존 데이터 충돌을 확인한다.

    Workbench 프로젝트는 ``name.wbpj`` 하나가 아니라 ``name_files`` 폴더와
    한 쌍으로 관리된다. 둘 중 하나라도 남아 있으면 기존 프로젝트로 취급하여,
    사용자가 명시적으로 덮어쓰기를 요청하지 않은 경우 실행을 중단한다.
    """
    prepare_workspace(config.workspace)
    requested = output or Path("results") / "cae-agent.wbpj"
    candidate = (
        requested.expanduser()
        if requested.is_absolute()
        else config.workspace.root / requested
    ).resolve()
    workspace_root = config.workspace.root.resolve()

    if not candidate.is_relative_to(workspace_root):
        raise ProjectError(
            "Workbench 프로젝트는 설정된 작업공간 내부에만 저장할 수 있습니다."
        )
    if candidate.suffix.lower() != ".wbpj":
        raise ProjectError("Workbench 프로젝트 확장자는 .wbpj여야 합니다.")

    companion = candidate.with_name(f"{candidate.stem}_files")
    if not overwrite and (candidate.exists() or companion.exists()):
        raise ProjectError(
            "기존 Workbench 프로젝트 또는 연결 데이터가 존재합니다. "
            "덮어쓰려면 --overwrite를 명시하세요."
        )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def build_create_project_journal(
    *,
    template_name: str,
    solver: str,
    output: Path,
    overwrite: bool,
) -> str:
    """해석 시스템을 만들고 지정 위치에 저장하는 Workbench 저널을 생성한다."""
    # Workbench IronPython이 Windows 한글 경로와 역슬래시를 일관되게 처리하도록
    # 절대경로를 슬래시 형식으로 변환한 뒤 repr 문자열 리터럴로 삽입한다.
    project_path = output.as_posix()
    return f"""
import json

template = GetTemplate(
    TemplateName={template_name!r},
    Solver={solver!r}
)
analysis_system = template.CreateSystem()
Save(FilePath={project_path!r}, Overwrite={overwrite!r})

wb_script_result = json.dumps({{
    "status": "created",
    "template_name": {template_name!r},
    "solver": {solver!r},
    "system_name": analysis_system.Name,
    "project_file": GetProjectFile()
}})
""".strip()


def _same_local_path(left: str, right: Path) -> bool:
    """Workbench 반환 경로를 Windows 대소문자 차이를 무시하고 비교한다."""
    left_normalized = os.path.normcase(os.path.abspath(left))
    right_normalized = os.path.normcase(os.path.abspath(str(right)))
    return left_normalized == right_normalized


def create_project(
    config: AppConfig,
    *,
    template_name: str = "Steady-State Thermal",
    solver: str = "ANSYS",
    output: Path | None = None,
    overwrite: bool = False,
    workbench: Any | None = None,
) -> ProjectResult:
    """현재 Workbench 세션에 시스템을 만들고 프로젝트를 저장한다."""
    if not template_name.strip():
        raise ProjectError("Workbench 템플릿 이름은 비어 있을 수 없습니다.")
    if not solver.strip():
        raise ProjectError("Workbench solver 이름은 비어 있을 수 없습니다.")

    destination = resolve_project_output(
        config,
        output,
        overwrite=overwrite,
    )
    journal = build_create_project_journal(
        template_name=template_name,
        solver=solver,
        output=destination,
        overwrite=overwrite,
    )
    active_workbench = workbench or connect_session(config)
    try:
        raw_result = active_workbench.run_script_string(journal)
        payload = (
            json.loads(raw_result)
            if isinstance(raw_result, str)
            else raw_result
        )
        if not isinstance(payload, dict):
            raise TypeError("결과가 JSON 객체가 아닙니다.")
        result = ProjectResult(
            status=str(payload["status"]),
            template_name=str(payload["template_name"]),
            solver=str(payload["solver"]),
            system_name=str(payload["system_name"]),
            project_file=str(payload["project_file"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ProjectError(
            f"Workbench가 잘못된 프로젝트 생성 결과를 반환했습니다: "
            f"{raw_result!r}"
        ) from error
    except Exception as error:
        raise ProjectError(
            f"Workbench 프로젝트 생성 요청이 실패했습니다: {error}"
        ) from error

    if result.status != "created":
        raise ProjectError(f"Workbench 프로젝트 생성이 실패했습니다: {result}")
    if result.template_name != template_name or result.solver != solver:
        raise ProjectError("요청한 템플릿 또는 solver와 생성 결과가 다릅니다.")
    if not result.system_name.strip():
        raise ProjectError("Workbench가 빈 시스템 이름을 반환했습니다.")
    if not _same_local_path(result.project_file, destination):
        raise ProjectError(
            "Workbench가 요청한 위치와 다른 경로에 프로젝트를 저장했습니다."
        )
    return result
