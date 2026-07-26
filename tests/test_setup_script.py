"""Windows 설치 스크립트의 안전한 dry-run과 주요 보호 규칙을 검증한다."""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "setup.ps1"


def test_setup_dry_run_does_not_create_environment(tmp_path: Path) -> None:
    """WhatIf 검증에서는 가상환경이나 설정 파일을 실제로 만들지 않아야 한다."""
    relative_venv = Path("test-install-dry-run")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SETUP),
            "-WhatIf",
            "-PythonExecutable",
            sys.executable,
            "-VirtualEnvironment",
            str(relative_venv),
            "-WithAnsys",
            "-WithDev",
            "-WithUI",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "검증 전용 모드" in completed.stdout
    assert ".[ansys,dev,ui]" in completed.stdout
    assert not (ROOT / relative_venv).exists()


def test_setup_documents_non_destructive_boundaries() -> None:
    """시스템 자동 설치와 기존 설정 덮어쓰기를 막는 문구가 유지되어야 한다."""
    source = SETUP.read_text(encoding="utf-8")

    assert "자동 설치하지 않습니다" in source
    assert "기존 설정 파일을 보존합니다" in source
    assert "저장소 내부여야 합니다" in source
    assert "Remove-Item" not in source
    assert "Invoke-WebRequest" not in source
