"""Workbench 세션 메타데이터와 PyWorkbench 호출 경계를 검증한다."""

import json
from pathlib import Path

import pytest

from cae_agent.core.config import load_config
from cae_agent.ansys.workbench import (
    WorkbenchError,
    WorkbenchSession,
    connect_session,
    load_session,
    request_stop,
    save_session,
    serve_session,
    workbench_paths,
)


def test_session_round_trip(tmp_path: Path) -> None:
    session_file = tmp_path / "session.json"
    expected = WorkbenchSession(
        host="127.0.0.1",
        port=50055,
        security="insecure",
        server_version="261",
        bridge_pid=1234,
    )

    save_session(session_file, expected)

    assert load_session(session_file) == expected


def test_corrupted_session_is_rejected(tmp_path: Path) -> None:
    session_file = tmp_path / "session.json"
    session_file.write_text("{broken", encoding="utf-8")

    with pytest.raises(WorkbenchError, match="손상"):
        load_session(session_file)


def test_remote_session_host_is_rejected(tmp_path: Path) -> None:
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(
            {
                "host": "example.com",
                "port": 50055,
                "security": "insecure",
                "server_version": "261",
                "bridge_pid": 1234,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(WorkbenchError, match="localhost"):
        load_session(session_file)


def test_connect_uses_validated_local_session(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    paths = workbench_paths(config)
    save_session(
        paths.session_file,
        WorkbenchSession(
            host="127.0.0.1",
            port=50055,
            security="insecure",
            server_version="261",
            bridge_pid=1234,
        ),
    )
    received: dict[str, object] = {}

    def connector(**kwargs):
        received.update(kwargs)
        return "connected"

    result = connect_session(config, connector=connector)

    assert result == "connected"
    assert received["host"] == "127.0.0.1"
    assert received["port"] == 50055
    assert received["client_workdir"] == str(paths.client)


def test_stop_request_stays_inside_workspace(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    paths = workbench_paths(config)
    save_session(
        paths.session_file,
        WorkbenchSession(
            host="127.0.0.1",
            port=50055,
            security="insecure",
            server_version="261",
            bridge_pid=1234,
        ),
    )

    stop_file = request_stop(config)

    assert stop_file == paths.stop_file
    assert stop_file.is_file()


def test_serve_writes_and_cleans_session_metadata(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    paths = workbench_paths(config)
    launch_arguments: dict[str, object] = {}

    class FakeWorkbench:
        server_version = "261"
        exited = False

        def run_script_string(self, _script: str) -> str:
            # 첫 ping 시 종료 요청을 만들어 대기 루프를 즉시 끝낸다. 실제 API를
            # 호출하지 않으면서 세션 파일 생성과 finally 정리를 함께 검증한다.
            paths.stop_file.touch()
            return "ok"

        def exit(self) -> None:
            self.exited = True

    fake_workbench = FakeWorkbench()

    def launcher(**kwargs):
        launch_arguments.update(kwargs)
        return fake_workbench

    serve_session(config, launcher=launcher, poll_interval=0)

    assert launch_arguments["version"] == "261"
    assert launch_arguments["port"] == 50055
    assert launch_arguments["show_gui"] is True
    assert fake_workbench.exited is True
    assert not paths.session_file.exists()
    assert not paths.stop_file.exists()


def test_missing_script_is_rejected_before_connecting(tmp_path: Path) -> None:
    from cae_agent.ansys.workbench import run_script

    config = load_config(current_directory=tmp_path)

    with pytest.raises(WorkbenchError, match="찾을 수 없습니다"):
        run_script(config, tmp_path / "missing.wbjn")
