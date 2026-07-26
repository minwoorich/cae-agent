"""Mechanical 세션 보안, 연결 시작과 내부 스크립트 실행을 검증한다."""

import json
from pathlib import Path

import pytest

from cae_agent.core.config import load_config
from cae_agent.ansys.mechanical import (
    MechanicalError,
    MechanicalSession,
    connect_mechanical,
    load_mechanical_session,
    mechanical_session_file,
    run_mechanical_script,
    save_mechanical_session,
    start_mechanical_session,
)


def test_session_round_trip_and_system_validation(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    path = mechanical_session_file(config, "SYS 1")
    expected = MechanicalSession("127.0.0.1", 7660, "SYS 1")

    save_mechanical_session(path, expected)

    assert load_mechanical_session(
        path,
        expected_system_name="SYS 1",
    ) == expected
    with pytest.raises(MechanicalError, match="이름이 다릅니다"):
        load_mechanical_session(path, expected_system_name="SYS")


def test_remote_host_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(
        json.dumps(
            {
                "host": "example.com",
                "port": 7660,
                "system_name": "SYS",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MechanicalError, match="localhost"):
        load_mechanical_session(path, expected_system_name="SYS")


def test_connect_uses_local_session(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    save_mechanical_session(
        mechanical_session_file(config, "SYS"),
        MechanicalSession("127.0.0.1", 7660, "SYS"),
    )
    received: dict[str, object] = {}

    def connector(**kwargs):
        received.update(kwargs)
        return "mechanical"

    result = connect_mechanical(
        config,
        system_name="SYS",
        connector=connector,
    )

    assert result == "mechanical"
    assert received == {
        "ip": "127.0.0.1",
        "port": 7660,
        "cleanup_on_exit": False,
    }


def test_start_server_saves_verified_session(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    class FakeWorkbench:
        def start_mechanical_server(self, *, system_name: str) -> int:
            assert system_name == "SYS"
            return 7660

    class FakeMechanical:
        def run_python_script(self, script: str) -> str:
            assert "analysis_count" in script
            return '{"status": "ok"}'

    session, status = start_mechanical_session(
        config,
        system_name="SYS",
        workbench=FakeWorkbench(),
        connector=lambda **_kwargs: FakeMechanical(),
    )

    assert session.port == 7660
    assert status == '{"status": "ok"}'
    assert load_mechanical_session(
        mechanical_session_file(config, "SYS"),
        expected_system_name="SYS",
    ) == session


def test_script_runs_only_inside_mechanical(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "setup.py"
    source.write_text("result = Model.Analyses.Count", encoding="utf-8")
    received: list[str] = []

    class FakeMechanical:
        def run_python_script(self, script: str) -> str:
            received.append(script)
            return "2"

    result = run_mechanical_script(
        config,
        source,
        system_name="SYS",
        run_id_factory=lambda: "fixed",
        mechanical=FakeMechanical(),
    )

    assert received == ["result = Model.Analyses.Count"]
    assert result.return_value == "2"
    assert result.staged_script.endswith("mechanical_fixed.py")
    assert source.read_text(encoding="utf-8") == "result = Model.Analyses.Count"


def test_script_execution_error_is_wrapped(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "setup.py"
    source.write_text("raise Exception()", encoding="utf-8")

    class FailingMechanical:
        def run_python_script(self, _script: str) -> str:
            raise RuntimeError("Mechanical failure")

    with pytest.raises(MechanicalError, match="실행이 실패"):
        run_mechanical_script(
            config,
            source,
            system_name="SYS",
            run_id_factory=lambda: "fixed",
            mechanical=FailingMechanical(),
        )
