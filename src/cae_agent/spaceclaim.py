"""Workbench Geometry 셀에서 SpaceClaim Python 스크립트를 실행한다.

입력 스크립트는 외부 CPython에서 import하거나 실행하지 않는다. 원본을 작업공간에
보존한 후 PyWorkbench 서버로 업로드하고, SpaceClaim 편집기 내부의 Python
환경에서만 실행한다.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from cae_agent.config import AppConfig, prepare_workspace
from cae_agent.workbench import (
    WorkbenchError,
    connect_session,
    workbench_paths,
)


class SpaceClaimError(RuntimeError):
    """SpaceClaim 스크립트 실행 결과를 신뢰할 수 없을 때 발생하는 오류."""


@dataclass(frozen=True, slots=True)
class SpaceClaimResult:
    """한 번의 SpaceClaim 실행에서 보존해야 할 결과."""

    run_id: str
    status: str
    system_name: str
    staged_script: str
    message: str

    def to_json(self) -> str:
        """CLI와 자동화 도구가 사용할 수 있도록 JSON으로 변환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def stage_script(
    config: AppConfig,
    script_file: Path,
    *,
    run_id: str,
) -> Path:
    """입력 스크립트를 변경하지 않고 작업공간에 고유 이름으로 복사한다."""
    source = script_file.expanduser().resolve()
    if not source.is_file():
        raise SpaceClaimError(
            f"SpaceClaim 스크립트를 찾을 수 없습니다: {source}"
        )
    if source.suffix.lower() != ".py":
        raise SpaceClaimError("SpaceClaim 스크립트는 .py 파일이어야 합니다.")

    prepare_workspace(config.workspace)
    destination = (
        config.workspace.generated_dir / f"spaceclaim_{run_id}.py"
    )
    # copy2를 사용해 원본의 수정 시각을 함께 보존하면 나중에 어떤 입력으로
    # 실행했는지 감사하거나 재현할 때 도움이 된다.
    shutil.copy2(source, destination)
    return destination


def build_workbench_journal(
    *,
    system_name: str,
    uploaded_script_name: str,
    wrapper_script_name: str,
    result_file_name: str,
    clear_geometry: bool,
) -> str:
    """SpaceClaim 실행과 명시적 결과 검증을 수행할 Workbench 저널을 만든다.

    Workbench의 ``RunScript``는 일부 SpaceClaim 내부 예외를 호출자에게 그대로
    전달하지 않는다. 따라서 별도 래퍼 스크립트가 성공 또는 traceback을 서버
    결과 파일에 기록하고, Workbench 저널이 그 파일을 다시 읽어 실패를 확정한다.
    """
    clear_statement = ""
    if clear_geometry:
        clear_statement = (
            'geometry.SendCommand(Language="Python", Command="ClearAll()")'
        )

    # repr로 문자열 리터럴을 만들면 시스템 이름에 공백이나 따옴표가 있어도
    # Workbench 저널 문법을 깨뜨리지 않는다. 업로드 파일명은 CAE Agent가 만든
    # UUID 기반 이름이므로 서버 작업폴더 밖의 경로를 주입할 수 없다.
    return f"""
import json
import os

system = GetSystem(Name={system_name!r})
geometry = system.GetContainer(ComponentName="Geometry")
geometry.Edit(IsSpaceClaimGeometry=True, Interactive=True)
{clear_statement}

source_path = os.path.join(
    GetServerWorkingDirectory(),
    {uploaded_script_name!r}
)
wrapper_path = os.path.join(
    GetServerWorkingDirectory(),
    {wrapper_script_name!r}
)
result_path = os.path.join(
    GetServerWorkingDirectory(),
    {result_file_name!r}
)

try:
    geometry.RunScript(ScriptFile=wrapper_path)
finally:
    # Workbench 호출 자체가 실패하더라도 편집기를 닫아 다음 자동화 명령이
    # 열린 SpaceClaim 창 때문에 교착되는 상황을 줄인다.
    geometry.Exit()

with open(result_path, "r") as result_stream:
    geometry_result = result_stream.read()

if not geometry_result.startswith("SUCCESS"):
    raise Exception(
        "SpaceClaim script execution failed:\\n" + geometry_result
    )

Save(Overwrite=True)
wb_script_result = json.dumps({{
    "status": "success",
    "system_name": system.Name,
    "message": geometry_result
}})
""".strip()


def create_wrapper_script(
    config: AppConfig,
    *,
    run_id: str,
    uploaded_script_name: str,
    result_file_name: str,
) -> Path:
    """원본을 ``execfile``로 실행하고 결과를 기록하는 SpaceClaim 래퍼를 만든다.

    사용자 소스를 거대한 ``SendCommand`` 문자열에 삽입하면 인코딩과 명령 길이에
    따라 V261에서 실행 결과 파일이 만들어지지 않을 수 있다. 작은 래퍼 파일에서
    원본 파일을 직접 실행하면 원본의 줄 번호를 유지하면서 예외도 기록할 수 있다.
    """
    paths = workbench_paths(config)
    source_path = (paths.server / uploaded_script_name).resolve()
    result_path = (paths.server / result_file_name).resolve()
    wrapper = (
        config.workspace.generated_dir
        / f"spaceclaim_{run_id}.wrapper.py"
    )
    wrapper.write_text(
        "\n".join(
            (
                "# -*- coding: utf-8 -*-",
                "import System",
                "import traceback",
                "try:",
                f"    execfile({str(source_path)!r})",
                "    Window.ActiveWindow.Document.Save()",
                (
                    "    System.IO.File.WriteAllText("
                    f"{str(result_path)!r}, 'SUCCESS')"
                ),
                "except Exception as exc:",
                "    System.IO.File.WriteAllText(",
                f"        {str(result_path)!r},",
                (
                    "        'ERROR ' + str(exc) + '\\n' "
                    "+ traceback.format_exc()"
                ),
                "    )",
            )
        ),
        encoding="utf-8",
    )
    return wrapper


def _parse_result(
    raw_result: Any,
    *,
    run_id: str,
    staged_script: Path,
    requested_system_name: str,
) -> SpaceClaimResult:
    """PyWorkbench 반환값을 검증된 SpaceClaim 결과 모델로 변환한다."""
    try:
        payload = (
            json.loads(raw_result)
            if isinstance(raw_result, str)
            else raw_result
        )
        if not isinstance(payload, dict):
            raise TypeError("결과가 JSON 객체가 아닙니다.")
        status = str(payload["status"])
        system_name = str(payload["system_name"])
        message = str(payload["message"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise SpaceClaimError(
            f"Workbench가 잘못된 SpaceClaim 결과를 반환했습니다: {raw_result!r}"
        ) from error

    if status != "success":
        raise SpaceClaimError(f"SpaceClaim 실행이 실패했습니다: {message}")
    if system_name != requested_system_name:
        raise SpaceClaimError(
            "요청한 Workbench 시스템과 실행 결과의 시스템이 다릅니다."
        )
    return SpaceClaimResult(
        run_id=run_id,
        status=status,
        system_name=system_name,
        staged_script=str(staged_script),
        message=message,
    )


def run_spaceclaim_script(
    config: AppConfig,
    script_file: Path,
    *,
    system_name: str,
    clear_geometry: bool = False,
    run_id_factory: Callable[[], str] | None = None,
    workbench: Any | None = None,
) -> SpaceClaimResult:
    """스크립트를 보존·업로드하고 지정 Geometry 셀에서 실행한다."""
    if not system_name.strip():
        raise SpaceClaimError("Workbench 시스템 이름은 비어 있을 수 없습니다.")

    create_run_id = run_id_factory or (lambda: uuid.uuid4().hex)
    run_id = create_run_id()
    staged = stage_script(config, script_file, run_id=run_id)
    result_name = f"spaceclaim_{run_id}.result.txt"
    wrapper = create_wrapper_script(
        config,
        run_id=run_id,
        uploaded_script_name=staged.name,
        result_file_name=result_name,
    )

    active_workbench = workbench or connect_session(config)
    try:
        # PyWorkbench는 서버 작업폴더에 basename으로 파일을 배치한다. UUID 기반
        # 이름을 사용하므로 동시 작업과 이전 실행 파일의 충돌을 피할 수 있다.
        active_workbench.upload_file(str(staged), show_progress=False)
        active_workbench.upload_file(str(wrapper), show_progress=False)
        journal = build_workbench_journal(
            system_name=system_name,
            uploaded_script_name=staged.name,
            wrapper_script_name=wrapper.name,
            result_file_name=result_name,
            clear_geometry=clear_geometry,
        )
        raw_result = active_workbench.run_script_string(journal)
    except Exception as error:
        if isinstance(error, (WorkbenchError, SpaceClaimError)):
            raise
        raise SpaceClaimError(
            f"SpaceClaim 스크립트 실행 요청이 실패했습니다: {error}"
        ) from error

    return _parse_result(
        raw_result,
        run_id=run_id,
        staged_script=staged,
        requested_system_name=system_name,
    )
