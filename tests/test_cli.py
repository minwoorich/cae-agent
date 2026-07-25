"""CAE Agent 최상위 명령행 인터페이스의 기본 동작을 검증한다."""

from types import SimpleNamespace

import pytest

from cae_agent import __version__
from cae_agent.cli import main
from cae_agent.doctor import CheckResult, CheckStatus


def test_cli_accepts_no_arguments() -> None:
    assert main([]) == 0


def test_cli_displays_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"cae-agent {__version__}"


def test_cli_displays_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "Ansys SpaceClaim and Mechanical" in capsys.readouterr().out


def test_doctor_command_returns_failure_for_failed_check(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """필수 진단 실패가 프로세스 실패 코드와 출력에 반영되는지 확인한다."""
    monkeypatch.setattr(
        "cae_agent.cli.run_checks",
        lambda _workspace: [
            CheckResult("ansys", CheckStatus.FAIL, "Ansys 없음")
        ],
    )

    assert main(["doctor"]) == 1
    assert "[FAIL] Ansys 없음" in capsys.readouterr().out


def test_config_show_displays_default_configuration(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """설정 파일이 없을 때 안전한 기본 설정이 출력되는지 확인한다."""
    monkeypatch.chdir(tmp_path)

    assert main(["config", "show", "--json"]) == 0

    output = capsys.readouterr().out
    assert '"version": "261"' in output
    assert '"provider": "codex"' in output


def test_mechanical_connect_prints_json_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """실제 서버 연결 후 결과 JSON 출력 경로의 import 누락을 방지한다."""
    monkeypatch.setattr(
        "cae_agent.cli.load_config",
        lambda _file: object(),
    )
    monkeypatch.setattr(
        "cae_agent.cli.start_mechanical_session",
        lambda _config, *, system_name: (
            SimpleNamespace(
                host="127.0.0.1",
                port=7660,
                system_name=system_name,
            ),
            '{"status": "ok"}',
        ),
    )

    assert main(["mechanical", "connect"]) == 0
    assert '"port": 7660' in capsys.readouterr().out


def test_run_agent_passes_execution_approval(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI가 실행 승인 값을 오케스트레이터에 빠짐없이 전달하는지 확인한다."""
    received: dict[str, object] = {}
    monkeypatch.chdir(tmp_path)

    def fake_loop(_config, **kwargs):
        received.update(kwargs)
        return SimpleNamespace(
            success=True,
            to_json=lambda: '{"success": true}',
        )

    monkeypatch.setattr("cae_agent.cli.run_repair_loop", fake_loop)
    assert (
        main(
            [
                "run-agent",
                "--target",
                "mechanical",
                "--prompt",
                "온도 결과 추가",
                "--approve-execution",
            ]
        )
        == 0
    )
    assert received["approve_execution"] is True
    assert '"success": true' in capsys.readouterr().out
