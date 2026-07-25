"""공개 릴리스의 버전과 필수 문서가 서로 일치하는지 검증한다."""

from pathlib import Path
import subprocess
import tomllib

from cae_agent import __version__


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.1.0"


def test_release_version_is_consistent() -> None:
    """소스 버전과 패키지 메타데이터가 동일한 정식 버전이어야 한다."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == EXPECTED_VERSION
    assert project["project"]["version"] == EXPECTED_VERSION
    assert not __version__.endswith((".dev0", "a0", "b0", "rc0"))


def test_release_documents_cover_scope_and_publication_boundary() -> None:
    """변경 이력과 릴리스 노트가 지원 범위와 수동 발행 경계를 설명해야 한다."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_notes = (
        ROOT / "docs" / "releases" / "v0.1.0.ko.md"
    ).read_text(encoding="utf-8")

    for required in ("## [0.1.0]", "Windows", "Python 3.11", "V261", "Codex"):
        assert required in changelog

    for required in (
        "릴리스 노트 초안",
        "--approve-execution",
        "GitHub Release",
        "PyPI",
        "사용자 승인",
    ):
        assert required in release_notes


def test_release_files_do_not_include_local_runtime_data() -> None:
    """Git이 추적하는 파일에는 로컬 설정과 작업공간 산출물이 없어야 한다."""
    forbidden = {
        "cae-agent.toml",
        ".venv",
        "workspace",
        "dist",
    }
    # 개발자의 로컬 파일 시스템에는 정상적으로 무시되는 가상환경과 작업공간이
    # 존재할 수 있다. 따라서 디렉터리를 직접 순회하지 않고 Git 추적 목록만
    # 확인해 로컬 산출물을 실수로 커밋하는 회귀를 차단한다.
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked_paths = {
        path
        for path in result.stdout.decode("utf-8").split("\0")
        if path
    }

    assert forbidden.isdisjoint({path.split("/", 1)[0] for path in tracked_paths})
