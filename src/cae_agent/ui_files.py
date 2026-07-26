"""CAE Agent UI의 파일 조회, 업로드와 상태 스냅숏 서비스를 제공한다.

NiceGUI 요소를 전혀 만들지 않으므로 브라우저 없이 단위 테스트할 수 있다.
파일 저장의 안전 경계도 화면 이벤트 코드와 분리해 다른 UI에서도 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from cae_agent.attachments import SUPPORTED_ATTACHMENT_EXTENSIONS
from cae_agent.config import AppConfig, prepare_workspace
from cae_agent.doctor import CheckResult, run_checks
from cae_agent.workbench import workbench_paths
from cae_agent.workspace import WorkspaceStatus, workspace_status


class UIError(RuntimeError):
    """로컬 UI가 안전하게 조회하거나 저장할 수 없는 요청의 오류."""


ALLOWED_UPLOAD_EXTENSIONS = SUPPORTED_ATTACHMENT_EXTENSIONS
MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


@dataclass(frozen=True, slots=True)
class StoredUpload:
    """검증을 통과해 입력 작업공간에 새로 저장된 파일 정보."""

    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PendingUploadReplacement:
    """사용자 승인 전 메모리에만 보관하는 중복 업로드 스냅숏."""

    target: Path
    content: bytes
    original_size: int
    original_mtime_ns: int


class UploadConflict(UIError):
    """같은 이름의 파일이 있어 교체 승인을 받아야 함을 나타낸다."""

    def __init__(self, pending: PendingUploadReplacement) -> None:
        super().__init__(f"같은 이름의 입력 파일이 이미 있습니다: {pending.target.name}")
        self.pending = pending


@dataclass(frozen=True, slots=True)
class InputFileSummary:
    """입력 라이브러리에 노출할 경로 없는 안전한 파일 메타데이터."""

    name: str
    extension: str
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """한 번의 새로고침에서 일관되게 표시할 대시보드 상태."""

    checks: tuple[CheckResult, ...]
    workspace: WorkspaceStatus
    workbench_session: bool
    mechanical_session_count: int
    recent_inputs: tuple[InputFileSummary, ...]
    recent_logs: tuple[str, ...]
    recent_results: tuple[str, ...]


def recent_files(directory: Path, *, limit: int = 8) -> tuple[str, ...]:
    """링크와 하위 폴더를 제외한 최근 일반 파일 이름만 반환한다."""
    if not directory.is_dir() or directory.is_symlink():
        return ()
    files = [
        path
        for path in directory.iterdir()
        if path.is_file() and not path.is_symlink()
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return tuple(path.name for path in files[:limit])


def input_file_summaries(
    directory: Path,
    *,
    limit: int = 100,
) -> tuple[InputFileSummary, ...]:
    """링크를 제외한 입력 파일을 최근 수정 순서의 메타데이터로 반환한다."""
    if not directory.is_dir() or directory.is_symlink():
        return ()
    summaries: list[InputFileSummary] = []
    for path in directory.iterdir():
        if not path.is_file() or path.is_symlink():
            continue
        try:
            file_stat = path.stat()
        except OSError:
            continue
        summaries.append(
            InputFileSummary(
                name=path.name,
                extension=path.suffix.lower() or "파일",
                size_bytes=file_stat.st_size,
                modified_at=datetime.fromtimestamp(
                    file_stat.st_mtime,
                ).astimezone(),
            )
        )
    summaries.sort(key=lambda item: item.modified_at, reverse=True)
    return tuple(summaries[:limit])


def dashboard_snapshot(
    config: AppConfig,
    *,
    checker: Callable[[Path], list[CheckResult]] = run_checks,
) -> DashboardSnapshot:
    """모델을 변경하지 않고 환경, 세션 메타데이터와 작업공간을 조회한다."""
    mechanical_runtime = config.workspace.root / ".runtime" / "mechanical"
    mechanical_sessions = (
        tuple(
            path
            for path in mechanical_runtime.glob("*.json")
            if path.is_file() and not path.is_symlink()
        )
        if mechanical_runtime.is_dir() and not mechanical_runtime.is_symlink()
        else ()
    )
    return DashboardSnapshot(
        checks=tuple(checker(config.workspace.root)),
        workspace=workspace_status(config),
        workbench_session=workbench_paths(config).session_file.is_file(),
        mechanical_session_count=len(mechanical_sessions),
        recent_inputs=input_file_summaries(config.workspace.input_dir),
        recent_logs=recent_files(config.workspace.logs_dir),
        recent_results=recent_files(config.workspace.results_dir),
    )


def format_bytes(value: int) -> str:
    """작은 입력부터 큰 해석 결과까지 읽기 쉬운 바이트 단위로 표시한다."""
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _validated_upload_target(
    config: AppConfig,
    *,
    filename: str,
    content: bytes,
) -> Path:
    """업로드 이름·형식·크기와 입력 폴더 경계를 검증해 대상 경로를 반환한다."""
    if not filename or Path(filename).name != filename:
        raise UIError("파일명에는 폴더 경로나 상위 경로를 포함할 수 없습니다.")
    if "/" in filename or "\\" in filename:
        raise UIError("파일명에는 경로 구분자를 포함할 수 없습니다.")
    if filename.endswith((" ", ".")) or re.search(r"[\x00-\x1f]", filename):
        raise UIError("파일명에 제어 문자나 끝 공백·마침표를 사용할 수 없습니다.")
    if Path(filename).stem.upper() in _WINDOWS_RESERVED_NAMES:
        raise UIError("Windows 예약 이름은 파일명으로 사용할 수 없습니다.")
    if Path(filename).suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise UIError(f"허용되지 않은 파일 형식입니다. 허용 형식: {allowed}")
    if not content:
        raise UIError("빈 파일은 업로드할 수 없습니다.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise UIError(
            f"파일 크기는 {format_bytes(MAX_UPLOAD_SIZE_BYTES)} 이하여야 합니다."
        )
    prepare_workspace(config.workspace)
    if config.workspace.input_dir.is_symlink():
        raise UIError("입력 폴더가 심볼릭 링크이므로 업로드를 차단했습니다.")
    target = config.workspace.input_dir / filename
    if target.is_symlink():
        raise UIError("같은 이름의 심볼릭 링크가 있어 업로드를 차단했습니다.")
    return target


def store_input_upload(
    config: AppConfig,
    *,
    filename: str,
    content: bytes,
) -> StoredUpload:
    """검증한 업로드를 새 파일로만 저장하고 중복이면 교체 승인을 준비한다."""
    target = _validated_upload_target(
        config,
        filename=filename,
        content=content,
    )
    if target.exists():
        try:
            current = target.stat()
        except OSError as error:
            raise UIError(f"기존 입력 파일을 확인할 수 없습니다: {error}") from error
        raise UploadConflict(
            PendingUploadReplacement(
                target=target,
                content=content,
                original_size=current.st_size,
                original_mtime_ns=current.st_mtime_ns,
            )
        )
    try:
        with target.open("xb") as stream:
            stream.write(content)
    except FileExistsError as error:
        raise UIError(f"같은 이름의 입력 파일이 이미 있습니다: {target.name}") from error
    except OSError as error:
        raise UIError(f"입력 파일을 저장할 수 없습니다: {error}") from error
    return StoredUpload(path=target, size_bytes=len(content))


def replace_input_upload(
    config: AppConfig,
    pending: PendingUploadReplacement,
) -> StoredUpload:
    """미리 본 기존 파일이 그대로일 때만 새 업로드로 원자적으로 교체한다."""
    if config.workspace.input_dir.is_symlink() or pending.target.is_symlink():
        raise UIError("승인 대상이 입력 폴더의 일반 파일이 아니므로 교체를 차단했습니다.")
    input_directory = config.workspace.input_dir.resolve()
    target = pending.target.resolve()
    if target.parent != input_directory:
        raise UIError("승인 대상이 입력 폴더의 일반 파일이 아니므로 교체를 차단했습니다.")
    try:
        current = target.stat()
    except OSError as error:
        raise UIError("승인 전에 기존 파일 상태가 변경되었습니다.") from error
    if (
        current.st_size != pending.original_size
        or current.st_mtime_ns != pending.original_mtime_ns
    ):
        raise UIError(
            "경고 모달을 연 뒤 기존 파일이 변경되었습니다. "
            "새로 업로드해 다시 확인하세요."
        )

    temporary = target.parent / f".{target.name}.{uuid4().hex}.upload"
    try:
        with temporary.open("xb") as stream:
            stream.write(pending.content)
        temporary.replace(target)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise UIError(f"입력 파일을 교체할 수 없습니다: {error}") from error

    audit_path = config.workspace.logs_dir / "upload-replacements.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "input_replaced",
        "filename": target.name,
        "previous_size_bytes": pending.original_size,
        "new_size_bytes": len(pending.content),
    }
    with audit_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return StoredUpload(path=target, size_bytes=len(pending.content))
