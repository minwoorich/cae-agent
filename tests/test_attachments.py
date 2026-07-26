"""채팅 첨부 파일의 자동 분류 규칙을 검증한다."""

from pathlib import Path

import pytest

from cae_agent.attachments import AttachmentKind, classify_attachment


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("열화상.PNG", AttachmentKind.IMAGE),
        ("package.step", AttachmentKind.GEOMETRY),
        ("analysis.mechdat", AttachmentKind.ANSYS_MODEL),
        ("material.csv", AttachmentKind.DATA),
    ],
)
def test_attachment_kind_is_detected_without_user_selection(
    filename: str,
    expected: AttachmentKind,
) -> None:
    """대소문자와 무관하게 파일 확장자만으로 전달 종류를 결정한다."""
    assert classify_attachment(Path(filename)) is expected


def test_unsupported_attachment_has_korean_message() -> None:
    """실행 파일처럼 지원하지 않는 형식은 자동 분류하지 않는다."""
    with pytest.raises(ValueError, match="지원하지 않는 첨부 파일 형식"):
        classify_attachment("unsafe.exe")
