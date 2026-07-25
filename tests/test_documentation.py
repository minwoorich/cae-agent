"""사용자 문서의 필수 경로, 안전 안내와 내부 링크를 검증한다."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GETTING_STARTED = ROOT / "docs" / "getting-started.ko.md"
TROUBLESHOOTING = ROOT / "docs" / "troubleshooting.ko.md"
BUG_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"


def test_guides_cover_first_run_and_execution_safety() -> None:
    """첫 실행 순서와 위험 옵션이 시작 문서에서 빠지지 않아야 한다."""
    source = GETTING_STARTED.read_text(encoding="utf-8")

    for required in (
        r".\setup.ps1 -WithAnsys",
        "workbench start",
        "workbench create-project",
        "mechanical",
        "generate",
        "run-agent",
        "--approve-execution",
        "--clear",
        "--overwrite",
        "workspace/generated",
        "workspace/logs",
    ):
        assert required in source


def test_troubleshooting_covers_major_components_and_secrets() -> None:
    """주요 실패 영역과 공개하면 안 되는 정보가 모두 설명돼야 한다."""
    source = TROUBLESHOOTING.read_text(encoding="utf-8")

    for required in (
        "Python",
        "Codex CLI",
        "Ansys",
        "Workbench",
        "Mechanical",
        "SpaceClaim",
        "라이선스",
        "PYTHONUTF8",
        "Personal Access Token",
        "API 키",
    ):
        assert required in source


def test_local_markdown_links_resolve() -> None:
    """두 가이드의 상대 Markdown 링크가 실제 저장소 파일을 가리켜야 한다."""
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://)([^)#]+)(?:#[^)]+)?\)")
    for document in (GETTING_STARTED, TROUBLESHOOTING):
        source = document.read_text(encoding="utf-8")
        for target in pattern.findall(source):
            resolved = (document.parent / target).resolve()
            assert resolved.exists(), f"{document}: 깨진 링크 {target}"


def test_bug_template_requires_secret_redaction() -> None:
    """버그 템플릿에서 두 민감정보 확인 항목을 필수로 유지한다."""
    source = BUG_TEMPLATE.read_text(encoding="utf-8")

    assert source.count("required: true") >= 7
    assert "토큰" in source
    assert "라이선스 정보" in source
    assert "비공개 CAD" in source
