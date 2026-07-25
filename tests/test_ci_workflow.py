"""GitHub Actions가 지원 버전과 배포 패키지를 계속 검증하는지 확인한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_covers_supported_python_versions_and_windows() -> None:
    """공개 지원 범위의 모든 Python 버전이 Windows 행렬에 있어야 한다."""
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: windows-latest" in source
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert f'"{version}"' in source
    assert "python -m pytest" in source
    assert "fail-fast: false" in source


def test_ci_validates_installer_and_built_wheel_without_secrets() -> None:
    """dry-run과 wheel smoke test를 수행하고 secret을 참조하지 않아야 한다."""
    source = WORKFLOW.read_text(encoding="utf-8")

    assert r".\setup.ps1 `" in source
    assert "-WhatIf `" in source
    assert "python -m build" in source
    assert r".package-test\Scripts\cae-agent.exe --version" in source
    assert "actions/upload-artifact@v4" in source
    assert "secrets." not in source
    assert 'PYTHONUTF8: "1"' in source
    assert 'PYTHONIOENCODING: "utf-8"' in source
