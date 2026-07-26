"""환경 진단 로직의 성공, 경고 및 실패 처리를 검증한다."""

from pathlib import Path

from cae_agent.core.doctor import (
    CheckResult,
    CheckStatus,
    check_command,
    check_operating_system,
    check_python,
    check_workspace,
    discover_ansys_installations,
    render_json,
    render_text,
)


def test_windows_is_supported() -> None:
    result = check_operating_system("Windows")

    assert result.status is CheckStatus.PASS


def test_unsupported_operating_system_fails() -> None:
    result = check_operating_system("Linux")

    assert result.status is CheckStatus.FAIL


def test_old_python_fails() -> None:
    result = check_python((3, 10, 9))

    assert result.status is CheckStatus.FAIL


def test_missing_optional_command_warns() -> None:
    result = check_command(
        "codex",
        required=False,
        finder=lambda _name: None,
    )

    assert result.status is CheckStatus.WARN


def test_missing_required_command_fails() -> None:
    result = check_command(
        "git",
        required=True,
        finder=lambda _name: None,
    )

    assert result.status is CheckStatus.FAIL


def test_ansys_installations_are_discovered_and_deduplicated(
    tmp_path: Path,
) -> None:
    program_files = tmp_path / "Program Files"
    version_root = program_files / "ANSYS Inc" / "v261"
    version_root.mkdir(parents=True)

    installations = discover_ansys_installations(
        environment={"AWP_ROOT261": str(version_root)},
        program_files=program_files,
    )

    assert installations == (version_root.resolve(),)


def test_workspace_is_created_and_writable(tmp_path: Path) -> None:
    workspace = tmp_path / "nested" / "workspace"

    result = check_workspace(workspace)

    assert result.status is CheckStatus.PASS
    assert workspace.is_dir()
    assert list(workspace.iterdir()) == []


def test_renderers_include_status_and_summary() -> None:
    results = [
        CheckResult("python", CheckStatus.PASS, "Python 정상"),
        CheckResult("ansys", CheckStatus.FAIL, "Ansys 없음"),
    ]

    text_output = render_text(results)
    json_output = render_json(results)

    assert "[PASS] Python 정상" in text_output
    assert "[FAIL] Ansys 없음" in text_output
    assert '"ok": false' in json_output
    assert '"status": "FAIL"' in json_output
