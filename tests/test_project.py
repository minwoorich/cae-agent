"""Workbench 프로젝트 생성의 경로 안전성과 결과 검증을 시험한다."""

import json
from pathlib import Path

import pytest

from cae_agent.config import load_config
from cae_agent.project import (
    ProjectError,
    build_create_project_journal,
    create_project,
    resolve_project_output,
)


def test_default_output_is_inside_workspace(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    output = resolve_project_output(config, None, overwrite=False)

    assert output == (
        config.workspace.root / "results" / "cae-agent.wbpj"
    )


def test_output_outside_workspace_is_rejected(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path / "project")

    with pytest.raises(ProjectError, match="작업공간 내부"):
        resolve_project_output(
            config,
            tmp_path / "outside.wbpj",
            overwrite=False,
        )


@pytest.mark.parametrize("existing_kind", ["project", "companion"])
def test_existing_project_data_requires_overwrite(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    config = load_config(current_directory=tmp_path)
    output = config.workspace.root / "results" / "model.wbpj"
    output.parent.mkdir(parents=True)
    if existing_kind == "project":
        output.touch()
    else:
        output.with_name("model_files").mkdir()

    with pytest.raises(ProjectError, match="--overwrite"):
        resolve_project_output(config, Path("results/model.wbpj"), overwrite=False)


def test_generated_journal_uses_requested_template_and_path(
    tmp_path: Path,
) -> None:
    output = tmp_path / "thermal.wbpj"

    journal = build_create_project_journal(
        template_name="Steady-State Thermal",
        solver="ANSYS",
        output=output,
        overwrite=False,
    )

    assert "TemplateName='Steady-State Thermal'" in journal
    assert "Solver='ANSYS'" in journal
    assert "Overwrite=False" in journal
    assert output.as_posix() in journal
    compile(journal, "<create-project-journal>", "exec")


def test_project_result_is_validated(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    destination = (
        config.workspace.root / "results" / "cae-agent.wbpj"
    ).resolve()

    class FakeWorkbench:
        def run_script_string(self, journal: str) -> str:
            assert "CreateSystem()" in journal
            return json.dumps(
                {
                    "status": "created",
                    "template_name": "Steady-State Thermal",
                    "solver": "ANSYS",
                    "system_name": "SYS",
                    "project_file": str(destination),
                }
            )

    result = create_project(config, workbench=FakeWorkbench())

    assert result.system_name == "SYS"
    assert Path(result.project_file) == destination


def test_wrong_returned_path_is_rejected(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    class FakeWorkbench:
        def run_script_string(self, _journal: str) -> str:
            return json.dumps(
                {
                    "status": "created",
                    "template_name": "Steady-State Thermal",
                    "solver": "ANSYS",
                    "system_name": "SYS",
                    "project_file": str(tmp_path / "wrong.wbpj"),
                }
            )

    with pytest.raises(ProjectError, match="다른 경로"):
        create_project(config, workbench=FakeWorkbench())
