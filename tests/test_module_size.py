"""핵심 Python 모듈이 다시 하나의 거대한 파일로 합쳐지는 것을 방지한다."""

from pathlib import Path


def test_source_modules_stay_below_one_thousand_lines() -> None:
    """프로덕션 모듈은 1,000줄 이하로 유지해 책임 분리를 강제한다."""
    source_directory = (
        Path(__file__).resolve().parents[1] / "src" / "cae_agent"
    )
    oversized = {
        str(path.relative_to(source_directory)): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in source_directory.rglob("*.py")
        if len(path.read_text(encoding="utf-8").splitlines()) > 1_000
    }

    assert oversized == {}, (
        "1,000줄을 넘는 모듈은 기능별 파일로 분리해야 합니다: "
        f"{oversized}"
    )
