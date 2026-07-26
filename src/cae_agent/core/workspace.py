"""CAE 작업공간의 사용량 조회와 보존 기간 기반 안전 정리를 제공한다.

사용자가 제공한 입력과 Workbench 프로젝트·해석 결과는 자동 정리 대상이 아니다.
현재 모듈은 다시 생성할 수 있는 스크립트, 로그와 Codex 임시 파일만 후보로
계산하며, 실제 삭제는 명시적 승인과 세션 비활성 상태를 모두 확인한 뒤 수행한다.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from cae_agent.core.config import AppConfig, WorkspaceConfig, prepare_workspace
from cae_agent.ansys.workbench import workbench_paths


class WorkspaceError(RuntimeError):
    """작업공간을 안전하게 조회하거나 정리할 수 없을 때 발생하는 오류."""


@dataclass(frozen=True, slots=True)
class DirectoryUsage:
    """작업공간의 한 논리 폴더가 사용하는 파일 수와 바이트 수."""

    name: str
    path: str
    file_count: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    """UI와 CLI가 함께 사용할 수 있는 작업공간 사용량 스냅숏."""

    root: str
    directories: tuple[DirectoryUsage, ...]
    total_file_count: int
    total_size_bytes: int
    active_session_files: tuple[str, ...]
    skipped_symlinks: tuple[str, ...]

    def to_json(self) -> str:
        """자동화 도구가 소비할 수 있도록 상태를 JSON 문자열로 변환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    """보존 기간과 경로 안전 검사를 통과한 삭제 후보 파일."""

    path: str
    size_bytes: int
    modified_at: str
    category: str


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """dry-run 또는 실제 정리의 후보, 삭제 및 실패 내역."""

    approved: bool
    dry_run: bool
    older_than_days: int
    candidates: tuple[CleanupCandidate, ...]
    candidate_size_bytes: int
    deleted: tuple[str, ...]
    deleted_size_bytes: int
    failures: tuple[str, ...]
    skipped_symlinks: tuple[str, ...]
    audit_log: str | None

    def to_json(self) -> str:
        """삭제 여부와 감사 경로를 포함한 결과를 JSON으로 변환한다."""
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _is_within(path: Path, root: Path) -> bool:
    """해석된 경로가 작업공간 루트 내부인지 판정한다."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _iter_regular_files(
    directory: Path,
    *,
    workspace_root: Path,
    skipped_symlinks: list[str],
) -> Iterable[Path]:
    """심볼릭 링크를 따라가지 않고 안전한 일반 파일만 순회한다."""
    if not directory.exists():
        return
    if directory.is_symlink():
        skipped_symlinks.append(str(directory))
        return
    if not _is_within(directory, workspace_root):
        raise WorkspaceError(
            f"작업공간 밖의 폴더는 조회할 수 없습니다: {directory}"
        )

    # os.walk의 followlinks=False와 디렉터리 목록 직접 필터링을 함께 사용해
    # Windows junction이나 심볼릭 링크가 외부 경로로 이어지는 상황을 막는다.
    for current_root, directory_names, file_names in os.walk(
        directory,
        followlinks=False,
    ):
        current = Path(current_root)
        safe_directories: list[str] = []
        for name in directory_names:
            child = current / name
            if child.is_symlink():
                skipped_symlinks.append(str(child))
            else:
                safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in file_names:
            candidate = current / name
            if candidate.is_symlink():
                skipped_symlinks.append(str(candidate))
                continue
            if not _is_within(candidate, workspace_root):
                raise WorkspaceError(
                    f"작업공간 밖으로 해석되는 파일을 발견했습니다: {candidate}"
                )
            if candidate.is_file():
                yield candidate


def _logical_directories(workspace: WorkspaceConfig) -> tuple[tuple[str, Path], ...]:
    """상태 화면에서 항상 같은 순서로 표시할 논리 폴더를 반환한다."""
    return (
        ("input", workspace.input_dir),
        ("generated", workspace.generated_dir),
        ("logs", workspace.logs_dir),
        ("results", workspace.results_dir),
        ("runtime", workspace.root / ".runtime"),
    )


def _active_session_files(config: AppConfig) -> tuple[Path, ...]:
    """정리와 충돌할 수 있는 Workbench·Mechanical 세션 파일을 찾는다."""
    runtime = config.workspace.root / ".runtime"
    possible: list[Path] = [workbench_paths(config).session_file]
    mechanical_runtime = runtime / "mechanical"
    if mechanical_runtime.is_dir() and not mechanical_runtime.is_symlink():
        possible.extend(mechanical_runtime.glob("*.json"))
    return tuple(path for path in possible if path.is_file())


def workspace_status(config: AppConfig) -> WorkspaceStatus:
    """폴더별 파일 수와 크기를 원본 변경 없이 계산한다."""
    root = config.workspace.root.resolve()
    skipped_symlinks: list[str] = []
    usages: list[DirectoryUsage] = []

    for name, directory in _logical_directories(config.workspace):
        files = tuple(
            _iter_regular_files(
                directory,
                workspace_root=root,
                skipped_symlinks=skipped_symlinks,
            )
        )
        usages.append(
            DirectoryUsage(
                name=name,
                path=str(directory),
                file_count=len(files),
                size_bytes=sum(path.stat().st_size for path in files),
            )
        )

    return WorkspaceStatus(
        root=str(root),
        directories=tuple(usages),
        total_file_count=sum(item.file_count for item in usages),
        total_size_bytes=sum(item.size_bytes for item in usages),
        active_session_files=tuple(
            str(path) for path in _active_session_files(config)
        ),
        skipped_symlinks=tuple(sorted(set(skipped_symlinks))),
    )


def _cleanup_directories(config: AppConfig) -> tuple[tuple[str, Path], ...]:
    """자동 정리가 허용된 최소 폴더 집합만 반환한다."""
    return (
        ("generated", config.workspace.generated_dir),
        ("logs", config.workspace.logs_dir),
        ("codex-runtime", config.workspace.root / ".runtime" / "codex"),
    )


def cleanup_candidates(
    config: AppConfig,
    *,
    older_than_days: int,
    now: datetime | None = None,
) -> tuple[tuple[CleanupCandidate, ...], tuple[str, ...]]:
    """보존 기간보다 오래된 안전 폴더의 일반 파일만 후보로 계산한다."""
    if older_than_days < 0:
        raise WorkspaceError("보존 기간은 0일 이상이어야 합니다.")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=older_than_days)
    root = config.workspace.root.resolve()
    skipped_symlinks: list[str] = []
    candidates: list[CleanupCandidate] = []

    for category, directory in _cleanup_directories(config):
        for path in _iter_regular_files(
            directory,
            workspace_root=root,
            skipped_symlinks=skipped_symlinks,
        ):
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if modified <= cutoff:
                candidates.append(
                    CleanupCandidate(
                        path=str(path),
                        size_bytes=stat.st_size,
                        modified_at=modified.isoformat(),
                        category=category,
                    )
                )

    candidates.sort(key=lambda item: item.path.casefold())
    return tuple(candidates), tuple(sorted(set(skipped_symlinks)))


def _remove_empty_directories(directory: Path, *, workspace_root: Path) -> None:
    """안전 폴더 자체는 남기고 그 아래의 빈 일반 디렉터리만 제거한다."""
    if not directory.is_dir() or directory.is_symlink():
        return
    children = sorted(
        (
            path
            for path in directory.rglob("*")
            if path.is_dir() and not path.is_symlink()
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for child in children:
        if _is_within(child, workspace_root):
            try:
                child.rmdir()
            except OSError:
                # 파일이 남았거나 다른 프로세스가 사용하는 폴더는 정상적인 보존
                # 대상으로 취급한다. 파일 삭제 실패는 별도로 결과에 기록된다.
                continue


def clean_workspace(
    config: AppConfig,
    *,
    older_than_days: int = 30,
    approve: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """안전 후보를 계산하고 명시적으로 승인된 경우에만 실제 삭제한다."""
    candidates, skipped_symlinks = cleanup_candidates(
        config,
        older_than_days=older_than_days,
        now=now,
    )
    candidate_size = sum(item.size_bytes for item in candidates)

    if not approve:
        return CleanupResult(
            approved=False,
            dry_run=True,
            older_than_days=older_than_days,
            candidates=candidates,
            candidate_size_bytes=candidate_size,
            deleted=(),
            deleted_size_bytes=0,
            failures=(),
            skipped_symlinks=skipped_symlinks,
            audit_log=None,
        )

    active_sessions = _active_session_files(config)
    if active_sessions:
        joined = ", ".join(str(path) for path in active_sessions)
        raise WorkspaceError(
            "실행 중이거나 종료가 확인되지 않은 세션 파일이 있어 정리를 "
            f"차단했습니다: {joined}"
        )

    prepare_workspace(config.workspace)
    root = config.workspace.root.resolve()
    deleted: list[str] = []
    failures: list[str] = []
    deleted_size = 0

    for item in candidates:
        path = Path(item.path)
        try:
            # 후보 계산과 실제 삭제 사이에 파일이 링크로 교체되는 시간차 공격을
            # 막기 위해 삭제 직전에도 링크와 경로 경계를 다시 확인한다.
            if path.is_symlink() or not _is_within(path, root):
                raise WorkspaceError("삭제 직전 경로 안전 검사가 실패했습니다.")
            path.unlink()
        except (OSError, WorkspaceError) as error:
            failures.append(f"{path}: {error}")
        else:
            deleted.append(str(path))
            deleted_size += item.size_bytes

    for _, directory in _cleanup_directories(config):
        _remove_empty_directories(directory, workspace_root=root)

    audit_time = now or datetime.now(timezone.utc)
    if audit_time.tzinfo is None:
        audit_time = audit_time.replace(tzinfo=timezone.utc)
    audit_path = (
        config.workspace.logs_dir
        / (
            f"workspace-clean-{audit_time.strftime('%Y%m%dT%H%M%SZ')}-"
            f"{uuid.uuid4().hex}.json"
        )
    )
    result = CleanupResult(
        approved=True,
        dry_run=False,
        older_than_days=older_than_days,
        candidates=candidates,
        candidate_size_bytes=candidate_size,
        deleted=tuple(deleted),
        deleted_size_bytes=deleted_size,
        failures=tuple(failures),
        skipped_symlinks=skipped_symlinks,
        audit_log=str(audit_path),
    )
    audit_path.write_text(result.to_json(), encoding="utf-8")
    return result


def render_workspace_status(status: WorkspaceStatus) -> str:
    """사람이 읽기 쉬운 폴더별 작업공간 상태를 만든다."""
    lines = [f"작업공간: {status.root}"]
    for item in status.directories:
        lines.append(
            f"- {item.name}: 파일 {item.file_count}개, "
            f"{item.size_bytes} bytes"
        )
    lines.append(
        f"합계: 파일 {status.total_file_count}개, "
        f"{status.total_size_bytes} bytes"
    )
    if status.active_session_files:
        lines.append(
            f"활성 세션 메타데이터: {len(status.active_session_files)}개"
        )
    if status.skipped_symlinks:
        lines.append(f"건너뛴 심볼릭 링크: {len(status.skipped_symlinks)}개")
    return "\n".join(lines)


def render_cleanup_result(result: CleanupResult) -> str:
    """dry-run과 실제 삭제 결과를 구분하는 사용자용 출력을 만든다."""
    mode = "DRY-RUN" if result.dry_run else "DELETE"
    lines = [
        f"모드: {mode}",
        f"보존 기간: {result.older_than_days}일",
        f"삭제 후보: {len(result.candidates)}개, "
        f"{result.candidate_size_bytes} bytes",
        f"실제 삭제: {len(result.deleted)}개, "
        f"{result.deleted_size_bytes} bytes",
    ]
    if result.failures:
        lines.append(f"삭제 실패: {len(result.failures)}개")
    if result.skipped_symlinks:
        lines.append(f"건너뛴 심볼릭 링크: {len(result.skipped_symlinks)}개")
    if result.audit_log is not None:
        lines.append(f"감사 로그: {result.audit_log}")
    if result.dry_run:
        for candidate in result.candidates:
            lines.append(
                f"- [{candidate.category}] {candidate.path} "
                f"({candidate.size_bytes} bytes)"
            )
        lines.append(
            "파일은 삭제되지 않았습니다. 실제 정리는 --approve가 필요합니다."
        )
    return "\n".join(lines)
