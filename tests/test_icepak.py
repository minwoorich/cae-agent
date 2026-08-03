"""Ansys 설치 없이 Icepak 어댑터의 경로, 연결 인자와 실행을 검증한다."""

import json
from pathlib import Path

import pytest

from cae_agent.ansys.icepak import (
    IcepakError,
    connect_icepak,
    create_icepak_project,
    icepak_status,
    pyaedt_version,
    run_icepak_script,
    select_aedt_version,
)
from cae_agent.core.config import load_config


def test_pyaedt_version_conversion() -> None:
    assert pyaedt_version("261") == "2026.1"
    assert pyaedt_version("2025.2") == "2025.2"


def test_installed_student_version_is_selected_as_fallback() -> None:
    assert select_aedt_version(
        "261",
        student_version=True,
        installed={"2025.2SV": r"C:\AnsysEM"},
    ) == "2025.2"


def test_connect_passes_verified_project_and_options(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    project = tmp_path / "thermal.aedt"
    project.write_text("", encoding="utf-8")
    received: dict[str, object] = {}

    class FakeIcepak:
        pass

    def factory(**kwargs):
        received.update(kwargs)
        return FakeIcepak()

    result = connect_icepak(
        config,
        project_file=project,
        design_name="Board",
        new_desktop=True,
        student_version=True,
        aedt_version="2025.2",
        factory=factory,
    )

    assert isinstance(result, FakeIcepak)
    assert received["project"] == str(project.resolve())
    assert received["design"] == "Board"
    assert received["version"] == "2025.2"
    assert received["new_desktop"] is True
    assert received["student_version"] is True
    assert received["close_on_exit"] is False


def test_invalid_project_extension_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "thermal.wbpj"
    project.write_text("", encoding="utf-8")
    with pytest.raises(IcepakError, match=".aedt"):
        connect_icepak(
            load_config(current_directory=tmp_path),
            project_file=project,
            factory=lambda **_kwargs: object(),
        )


def test_create_project_is_limited_to_generated_and_preserves_existing(
    tmp_path: Path,
) -> None:
    config = load_config(current_directory=tmp_path)
    output = config.workspace.generated_dir / "icepak" / "smoke.aedt"

    class FakeIcepak:
        design_name = "Smoke"
        released = False

        def save_project(self, path: str) -> None:
            Path(path).write_text("project", encoding="utf-8")

        def release_desktop(self, **kwargs) -> None:
            self.released = kwargs == {"close_projects": True, "close_desktop": True}

    result = create_icepak_project(
        config,
        output=output,
        design_name="Smoke",
        student_version=True,
        factory=lambda **_kwargs: FakeIcepak(),
    )

    assert result.status == "created"
    assert output.read_text(encoding="utf-8") == "project"
    with pytest.raises(IcepakError, match="덮어쓸"):
        create_icepak_project(
            config,
            output=output,
            factory=lambda **_kwargs: FakeIcepak(),
        )
    with pytest.raises(IcepakError, match="generated"):
        create_icepak_project(
            config,
            output=tmp_path / "outside.aedt",
            factory=lambda **_kwargs: FakeIcepak(),
        )


def test_status_and_script_execution(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    project = tmp_path / "thermal.aedt"
    project.write_text("", encoding="utf-8")
    script = tmp_path / "set_power.py"
    script.write_text(
        'result = {"project": icepak.project_name, "power": 25}\n',
        encoding="utf-8",
    )

    class FakeIcepak:
        project_name = "thermal"
        design_name = "Board"
        solution_type = "SteadyState"

    app = FakeIcepak()
    status = json.loads(icepak_status(app))
    result = run_icepak_script(
        config,
        script,
        project_file=project,
        app=app,
        run_id_factory=lambda: "fixed",
    )

    assert status["design"] == "Board"
    assert result.status == "success"
    assert "'power': 25" in result.return_value
    assert result.staged_script.endswith("generated\\icepak\\icepak_fixed.py")


def test_owned_new_desktop_is_released_after_script(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    project = tmp_path / "thermal.aedt"
    project.write_text("", encoding="utf-8")
    script = tmp_path / "run.py"
    script.write_text("result = 'ok'\n", encoding="utf-8")

    class FakeIcepak:
        project_name = "thermal"
        design_name = "Board"
        released = False

        def release_desktop(self, **kwargs) -> None:
            self.released = kwargs == {"close_projects": True, "close_desktop": True}

    app = FakeIcepak()
    result = run_icepak_script(
        config,
        script,
        project_file=project,
        new_desktop=True,
        factory=lambda **_kwargs: app,
    )

    assert result.return_value == "ok"
    assert app.released is True
