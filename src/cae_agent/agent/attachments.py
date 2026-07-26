"""채팅 첨부 파일을 사용자 입력 없이 안전하게 자동 분류한다."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path


class AttachmentKind(StrEnum):
    """Codex 전달 방식과 UI 표시에 사용하는 첨부 파일 종류."""

    IMAGE = "이미지"
    GEOMETRY = "CAD/형상"
    ANSYS_MODEL = "Ansys 모델"
    DATA = "데이터/문서"


IMAGE_EXTENSIONS = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".webp"})
GEOMETRY_EXTENSIONS = frozenset({".iges", ".igs", ".scdoc", ".step", ".stp"})
ANSYS_MODEL_EXTENSIONS = frozenset({".mechdat", ".wbpj"})
DATA_EXTENSIONS = frozenset({".csv", ".json", ".txt"})

SUPPORTED_ATTACHMENT_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | GEOMETRY_EXTENSIONS
    | ANSYS_MODEL_EXTENSIONS
    | DATA_EXTENSIONS
)


def classify_attachment(path: Path | str) -> AttachmentKind:
    """확장자를 기준으로 지원 첨부 종류를 결정한다.

    사용자가 파일 종류를 별도로 선택하게 하지 않는다. 확장자는 전달 방식만
    결정하며, 파일 내용이 올바른 CAE 모델인지에 대한 검증은 실제 가져오기나
    해석 전에 Ansys와 별도 검증 단계에서 수행해야 한다.
    """
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return AttachmentKind.IMAGE
    if suffix in GEOMETRY_EXTENSIONS:
        return AttachmentKind.GEOMETRY
    if suffix in ANSYS_MODEL_EXTENSIONS:
        return AttachmentKind.ANSYS_MODEL
    if suffix in DATA_EXTENSIONS:
        return AttachmentKind.DATA
    raise ValueError(f"지원하지 않는 첨부 파일 형식입니다: {suffix or '(확장자 없음)'}")
