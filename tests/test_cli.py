"""CAE Agent 최상위 명령행 인터페이스의 기본 동작을 검증한다."""

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
