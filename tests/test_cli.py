"""CAE Agent 최상위 명령행 인터페이스의 기본 동작을 검증한다."""

import pytest

from cae_agent import __version__
from cae_agent.cli import main


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
