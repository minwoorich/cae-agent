"""CAE Agent의 읽기 중심 로컬 NiceGUI 대시보드를 구성한다.

UI는 기존 서비스 계층을 직접 호출하며 셸 명령의 텍스트 출력을 다시 파싱하지
않는다. 화면을 열거나 새로고침하는 동작은 진단과 상태 조회만 수행하고, 실제
파일 정리는 dry-run 결과를 표시한 뒤 별도 확인 대화상자에서 승인해야 한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from cae_agent.attachments import (
    SUPPORTED_ATTACHMENT_EXTENSIONS,
    classify_attachment,
)
from cae_agent.approval import (
    ApprovalRequest,
    ApprovalRisk,
    requires_manual_approval,
)
from cae_agent.chat import (
    ChatError,
    ChatMessage,
    ChatSession,
    ChatStatus,
    MessageDetail,
    MessageDetailKind,
    MessageRole,
)
from cae_agent.codex_app_server import (
    CodexAppServerClient,
    CodexAppServerError,
)
from cae_agent.config import AppConfig, prepare_workspace
from cae_agent.doctor import CheckResult, run_checks
from cae_agent.workbench import (
    WorkbenchError,
    connect_session,
    load_session,
    ping_session,
    workbench_paths,
)
from cae_agent.workspace import (
    CleanupResult,
    WorkspaceError,
    WorkspaceStatus,
    clean_workspace,
    workspace_status,
)


class UIError(RuntimeError):
    """로컬 대시보드를 안전하게 구성하거나 시작할 수 없을 때의 오류."""


@dataclass(frozen=True, slots=True)
class ServiceConnection:
    """UI에 표시할 로컬 서비스의 실제 연결 확인 결과."""

    connected: bool
    label: str
    detail: str


@dataclass(slots=True)
class ChatProgressStep:
    """한 assistant 응답에서 사용자에게 공개할 관찰 가능한 작업 단계."""

    step_id: str
    title: str
    status: str = "running"
    detail: str = ""
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None


def probe_workbench_connection(config: AppConfig) -> ServiceConnection:
    """세션 파일뿐 아니라 Workbench의 실제 응답까지 확인한다.

    세션 JSON은 재연결 주소일 뿐 살아 있는 프로세스를 보장하지 않는다. 따라서
    메타데이터를 검증한 다음 Workbench에 연결해 가벼운 프로젝트 경로 조회가
    성공한 경우에만 연결됨으로 판정한다.
    """
    session_path = workbench_paths(config).session_file
    if not session_path.is_file():
        return ServiceConnection(
            connected=False,
            label="Workbench · 세션 없음",
            detail="먼저 Workbench 브리지를 시작해야 합니다.",
        )
    try:
        session = load_session(session_path)
        response = ping_session(connect_session(config))
    except (WorkbenchError, OSError) as error:
        return ServiceConnection(
            connected=False,
            label="Workbench · 연결 끊김",
            detail=(
                f"{error} `cae-agent workbench status`로 다시 확인해 주세요."
            ),
        )
    return ServiceConnection(
        connected=True,
        label=f"Workbench {session.server_version} · 연결됨",
        detail=f"실제 ping 응답: {response}",
    )


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


def _recent_files(directory: Path, *, limit: int = 8) -> tuple[str, ...]:
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
    """링크를 제외한 입력 파일을 최근 수정 순서의 메타데이터로 반환한다.

    UI에는 절대 경로를 전달하지 않는다. 파일이 조회 도중 사라지는 경우에는
    전체 라이브러리를 실패시키지 않고 해당 항목만 건너뛴다.
    """
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
        recent_logs=_recent_files(config.workspace.logs_dir),
        recent_results=_recent_files(config.workspace.results_dir),
    )


def _format_bytes(value: int) -> str:
    """작은 바이트 값부터 큰 해석 결과까지 읽기 쉬운 단위로 표시한다."""
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def store_input_upload(
    config: AppConfig,
    *,
    filename: str,
    content: bytes,
) -> StoredUpload:
    """업로드 파일을 검증하고 기존 파일을 건드리지 않은 채 원자적으로 저장한다.

    브라우저의 파일 선택 제한은 우회될 수 있으므로 파일명, 확장자와 크기를
    서버에서 다시 검사한다. ``xb`` 모드로 새 파일만 생성해 동시에 같은 이름이
    업로드되더라도 기존 사용자 입력을 덮어쓰지 않는다.
    """
    if not filename or Path(filename).name != filename:
        raise UIError("파일명에는 폴더 경로나 상위 경로를 포함할 수 없습니다.")
    if "/" in filename or "\\" in filename:
        raise UIError("파일명에는 경로 구분자를 포함할 수 없습니다.")
    if filename.endswith((" ", ".")) or re.search(r"[\x00-\x1f]", filename):
        raise UIError("파일명에 제어 문자나 끝 공백·마침표를 사용할 수 없습니다.")
    if Path(filename).stem.upper() in _WINDOWS_RESERVED_NAMES:
        raise UIError("Windows 예약 이름은 파일명으로 사용할 수 없습니다.")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise UIError(f"허용되지 않은 파일 형식입니다. 허용 형식: {allowed}")
    if not content:
        raise UIError("빈 파일은 업로드할 수 없습니다.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise UIError(
            "파일 크기는 "
            f"{_format_bytes(MAX_UPLOAD_SIZE_BYTES)} 이하여야 합니다."
        )

    prepare_workspace(config.workspace)
    input_directory = config.workspace.input_dir
    if input_directory.is_symlink():
        raise UIError("입력 폴더가 심볼릭 링크이므로 업로드를 차단했습니다.")

    target = input_directory / filename
    if target.is_symlink():
        raise UIError("같은 이름의 심볼릭 링크가 있어 업로드를 차단했습니다.")
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
        raise UIError(
            f"같은 이름의 입력 파일이 이미 있습니다: {filename}"
        ) from error
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


def build_dashboard(config: AppConfig, *, ui_module: Any) -> None:
    """주입된 NiceGUI 모듈에 구조화된 로컬 CAE 대시보드를 등록한다.

    화면은 개요, 입력 파일, 활동과 유지관리로 분리한다. 현재 단계에서는
    대화 기능을 구현한 것처럼 보이지 않도록 다음 단계임을 명확히 알리고,
    사용자가 가장 먼저 필요한 업로드와 환경 상태에 빠르게 접근하게 한다.
    """
    ui = ui_module
    ui.colors(
        primary="#38bdf8",
        secondary="#22d3ee",
        accent="#f59e0b",
        positive="#34d399",
        negative="#fb7185",
        dark="#08111f",
    )
    ui.dark_mode().enable()
    ui.add_css(
        """
        :root {
            --cae-bg: #08111f;
            --cae-surface: #0d1a2b;
            --cae-surface-raised: #122238;
            --cae-border: rgba(148, 163, 184, 0.16);
            --cae-text: #e5eefb;
            --cae-muted: #8fa5bf;
            --cae-primary: #38bdf8;
            --cae-positive: #34d399;
            --cae-warning: #f59e0b;
            --cae-negative: #fb7185;
        }
        body, .q-page, .nicegui-content {
            background:
                radial-gradient(circle at 80% -10%, rgba(56, 189, 248, 0.10), transparent 32rem),
                var(--cae-bg);
            color: var(--cae-text);
        }
        .cae-header {
            background: rgba(8, 17, 31, 0.88);
            border-bottom: 1px solid var(--cae-border);
            backdrop-filter: blur(18px);
        }
        .cae-drawer {
            background: #0a1525;
            border-right: 1px solid var(--cae-border);
        }
        .cae-drawer .q-tab {
            justify-content: flex-start;
            min-height: 48px;
            border-radius: 12px;
            color: var(--cae-muted);
        }
        .cae-drawer .q-tab--active {
            color: var(--cae-text);
            background: rgba(56, 189, 248, 0.12);
        }
        .cae-panel {
            background: linear-gradient(145deg, rgba(18, 34, 56, 0.94), rgba(13, 26, 43, 0.94));
            border: 1px solid var(--cae-border);
            border-radius: 18px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.18);
        }
        .cae-metric {
            min-width: 190px;
            flex: 1 1 190px;
        }
        .cae-eyebrow {
            color: var(--cae-primary);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }
        .cae-muted { color: var(--cae-muted); }
        .cae-hero-copy {
            max-width: 100%;
            overflow-wrap: anywhere;
            white-space: normal;
        }
        .cae-actions {
            display: flex;
            flex-wrap: wrap !important;
        }
        .cae-upload {
            border: 1px dashed rgba(56, 189, 248, 0.55);
            border-radius: 16px;
            background: rgba(56, 189, 248, 0.05);
        }
        .cae-file-row {
            border-bottom: 1px solid var(--cae-border);
            padding: 0.7rem 0;
        }
        .cae-file-row:last-child { border-bottom: 0; }
        .cae-danger {
            border-color: rgba(251, 113, 133, 0.34);
            background: rgba(127, 29, 29, 0.12);
        }
        .q-dialog__backdrop {
            background: rgba(2, 6, 23, 0.86) !important;
            backdrop-filter: blur(8px);
        }
        .cae-dialog-card {
            background: #0d1a2b !important;
            color: var(--cae-text) !important;
            border: 1px solid rgba(148, 163, 184, 0.42) !important;
            box-shadow:
                0 28px 90px rgba(0, 0, 0, 0.72),
                0 0 0 1px rgba(56, 189, 248, 0.08) !important;
            opacity: 1 !important;
        }
        .cae-dialog-card.cae-danger {
            background:
                linear-gradient(145deg, #241827, #0d1a2b 58%) !important;
            border-color: rgba(251, 113, 133, 0.58) !important;
        }
        .cae-chat-stream {
            flex: 1 1 auto;
            min-height: 0;
            overflow-y: auto;
            scroll-behavior: smooth;
            padding: 1.5rem clamp(0.5rem, 4vw, 4rem);
        }
        .cae-chat-page {
            height: calc(100vh - 64px);
            min-height: 680px;
            overflow: hidden;
        }
        .cae-chat-shell {
            flex: 1 1 auto;
            min-height: 0;
            background: rgba(8, 17, 31, 0.46);
            border: 1px solid var(--cae-border);
            border-radius: 22px;
            overflow: hidden;
        }
        .cae-chat-statusbar {
            min-height: 54px;
            background: rgba(10, 21, 37, 0.92);
            border-bottom: 1px solid var(--cae-border);
            backdrop-filter: blur(16px);
        }
        .cae-message {
            width: auto;
            max-width: min(980px, 88%);
            border: 1px solid var(--cae-border);
            border-radius: 18px;
            padding: 1rem 1.15rem;
        }
        .cae-message-user {
            align-self: flex-end;
            background: rgba(56, 189, 248, 0.13);
            border-color: rgba(56, 189, 248, 0.30);
        }
        .cae-message-assistant {
            align-self: flex-start;
            background: rgba(18, 34, 56, 0.58);
            border-color: transparent;
        }
        .cae-message-system {
            align-self: center;
            background: rgba(148, 163, 184, 0.08);
        }
        .cae-message-error {
            align-self: flex-start;
            background: rgba(127, 29, 29, 0.18);
            border-color: rgba(251, 113, 133, 0.34);
        }
        .cae-message-body {
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            line-height: 1.7;
        }
        .cae-progress-panel {
            border: 1px solid rgba(148, 163, 184, 0.20);
            border-radius: 14px;
            background: rgba(2, 6, 23, 0.20);
        }
        .cae-progress-step {
            padding: 0.4rem 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.12);
        }
        .cae-progress-step:last-child { border-bottom: 0; }
        .cae-progress-detail {
            overflow-wrap: anywhere;
            white-space: pre-wrap;
        }
        .cae-composer {
            position: sticky;
            bottom: 0;
            z-index: 2;
            border: 0 !important;
            border-radius: 0 !important;
            background: linear-gradient(
                180deg,
                rgba(8, 17, 31, 0),
                rgba(8, 17, 31, 0.98) 24%
            ) !important;
            backdrop-filter: blur(16px);
            box-shadow: none !important;
        }
        .cae-composer-inner {
            width: min(920px, 100%);
            margin: 0 auto;
            padding: 0.55rem 0.65rem;
            border: 1px solid rgba(148, 163, 184, 0.32);
            border-radius: 26px;
            background: #111d2e;
            box-shadow: 0 10px 32px rgba(0, 0, 0, 0.24);
        }
        .cae-composer-inner:focus-within {
            border-color: rgba(148, 163, 184, 0.56);
        }
        .cae-hidden-upload { display: none !important; }
        .cae-chat-input .q-field__control {
            min-height: 42px !important;
            padding: 0 0.35rem !important;
            color: var(--cae-text);
        }
        .cae-chat-input textarea {
            max-height: 180px;
            line-height: 1.55 !important;
            resize: none !important;
        }
        .cae-composer-feedback:empty { display: none; }
        .cae-composer-actions { min-height: 38px; }
        .cae-composer .q-chip { max-width: min(360px, 76vw); }
        .cae-composer .q-chip__content {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .q-tab-panels, .q-tab-panel {
            background: transparent !important;
        }
        .q-tab-panel {
            overflow-x: hidden;
        }
        .cae-page, .cae-panel {
            box-sizing: border-box;
            max-width: 100%;
        }
        @media (max-width: 900px) {
            body { overflow-x: hidden; }
            .cae-page {
                width: 100% !important;
                padding: 1rem !important;
            }
            .cae-hero-title { font-size: 1.75rem !important; }
            .cae-metric {
                min-width: 100% !important;
                flex-basis: 100% !important;
            }
            .cae-header-status { display: none !important; }
            .cae-actions .q-btn {
                width: 100%;
            }
            .cae-brand-subtitle { display: none !important; }
            .cae-chat-page {
                min-height: 600px;
                height: calc(100vh - 56px);
            }
            .cae-chat-stream { padding: 1rem; }
            .cae-message { max-width: 100% !important; }
            .cae-composer { padding: 0.65rem !important; }
            .cae-composer-inner { border-radius: 22px; }
        }
        """
    )

    cleanup_state: dict[str, CleanupResult | int | None] = {
        "preview": None,
        "days": 30,
    }

    def section_heading(
        eyebrow: str,
        title: str,
        description: str,
    ) -> None:
        """각 화면의 목적과 안전 경계를 같은 계층으로 표시한다."""
        with ui.column().classes("gap-1"):
            ui.label(eyebrow).classes("cae-eyebrow")
            ui.label(title).classes("text-2xl font-bold")
            ui.label(description).classes("cae-muted text-sm max-w-3xl")

    def status_badge(label: str, *, active: bool, icon: str) -> None:
        """색상에만 의존하지 않는 아이콘·문자 상태 배지를 그린다."""
        color = "positive" if active else "grey-6"
        text = "감지됨" if active else "없음"
        ui.badge(
            f"{label} · {text}",
            color=color,
        ).props(f"outline rounded icon={icon}").classes("px-3 py-2")

    def file_list(
        names: tuple[str, ...],
        *,
        empty_text: str,
        icon: str,
    ) -> None:
        """최근 파일 목록을 파일명과 아이콘이 있는 일관된 행으로 표시한다."""
        if not names:
            with ui.column().classes("items-center w-full py-8 gap-2"):
                ui.icon(icon).classes("text-3xl cae-muted")
                ui.label(empty_text).classes("cae-muted text-sm")
            return
        for name in names:
            with ui.row().classes(
                "cae-file-row w-full items-center justify-between no-wrap"
            ):
                with ui.row().classes("items-center gap-3 min-w-0 no-wrap"):
                    ui.icon(icon).classes("text-primary text-xl")
                    ui.label(name).classes("text-sm truncate")
                ui.badge(Path(name).suffix.lower() or "file").props(
                    "outline color=grey-6"
                )

    drawer = ui.left_drawer(value=None).props(
        "width=248 bordered breakpoint=800"
    ).classes("cae-drawer px-3 py-5")

    with ui.header().classes(
        "cae-header h-16 items-center justify-between px-4 md:px-6"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.button(
                icon="menu",
                on_click=drawer.toggle,
            ).props("flat round dense aria-label='내비게이션 열기'")
            ui.icon("view_in_ar").classes("text-primary text-2xl")
            with ui.column().classes("gap-0"):
                ui.label("CAE Agent").classes("font-bold leading-tight")
                ui.label("Engineering workspace").classes(
                    "cae-brand-subtitle text-xs cae-muted leading-tight"
                )
        with ui.row().classes("cae-header-status items-center gap-2"):
            ui.badge("LOCAL ONLY", color="positive").props(
                "outline rounded"
            )
            ui.badge("UI v0.2", color="primary").props("rounded")

    with drawer:
        ui.label("WORKSPACE").classes("cae-eyebrow px-3 mb-2")
        with ui.tabs().props("vertical no-caps indicator-color=transparent") \
                .classes("w-full") as navigation:
            overview_tab = ui.tab(
                "overview",
                label="개요",
                icon="space_dashboard",
            )
            chat_tab = ui.tab(
                "chat",
                label="대화",
                icon="forum",
            )
            activity_tab = ui.tab(
                "activity",
                label="로그와 결과",
                icon="monitor_heart",
            )
            maintenance_tab = ui.tab(
                "maintenance",
                label="유지관리",
                icon="settings_suggest",
            )
        ui.separator().classes("my-5 opacity-20")
        with ui.card().classes("cae-panel p-4 gap-2"):
            ui.icon("science").classes("text-accent text-2xl")
            ui.label("Codex 승인 기반 실행").classes("font-semibold")
            ui.label(
                "명령 실행과 파일 변경은 승인 카드에서 확인한 "
                "정확한 요청 한 건만 허용됩니다."
            ).classes("cae-muted text-xs leading-relaxed")
            ui.badge("APPROVAL REQUIRED", color="accent").props("outline")

    @ui.refreshable
    def overview_content() -> None:
        """환경과 작업공간의 핵심 상태를 첫 화면에서 요약한다."""
        try:
            snapshot = dashboard_snapshot(config)
        except (OSError, WorkspaceError) as error:
            with ui.card().classes("cae-panel w-full p-5"):
                ui.label(f"상태 조회 실패: {error}").classes("text-negative")
            return

        with ui.card().classes(
            "cae-panel w-full p-6 md:p-8 gap-5 overflow-hidden"
        ):
            ui.label("CODEX-FIRST CAE WORKSPACE").classes("cae-eyebrow")
            ui.label("설계부터 결과까지, 한 작업공간에서").classes(
                "cae-hero-title cae-hero-copy text-3xl md:text-4xl "
                "font-bold max-w-3xl"
            )
            ui.label(
                "입력 파일을 안전하게 보관하고 환경·세션·결과를 확인하세요. "
                "화면 조회와 업로드만으로 Ansys 모델은 변경되지 않습니다."
            ).classes(
                "cae-hero-copy cae-muted text-base max-w-3xl leading-relaxed"
            )
            with ui.row().classes("cae-actions w-full gap-3"):
                ui.button(
                    "채팅에서 파일 첨부",
                    icon="attach_file",
                    on_click=lambda: navigation.set_value(chat_tab),
                ).props("unelevated rounded no-caps")
                ui.button(
                    "상태 새로고침",
                    icon="refresh",
                    on_click=overview_content.refresh,
                ).props("outline rounded no-caps")

        pass_count = sum(
            check.status.value == "PASS" for check in snapshot.checks
        )
        warning_count = sum(
            check.status.value == "WARN" for check in snapshot.checks
        )
        failure_count = sum(
            check.status.value == "FAIL" for check in snapshot.checks
        )
        with ui.row().classes("w-full gap-4 items-stretch"):
            metrics = (
                (
                    "환경 검사",
                    f"{pass_count}/{len(snapshot.checks)} 통과",
                    "verified",
                    "positive" if not failure_count else "negative",
                ),
                (
                    "주의 항목",
                    f"{warning_count + failure_count}개",
                    "warning_amber",
                    "accent" if warning_count + failure_count else "positive",
                ),
                (
                    "작업공간",
                    _format_bytes(snapshot.workspace.total_size_bytes),
                    "hard_drive",
                    "primary",
                ),
                (
                    "입력 파일",
                    f"{len(snapshot.recent_inputs)}개 최근 항목",
                    "description",
                    "secondary",
                ),
            )
            for title, value, icon, color in metrics:
                with ui.card().classes("cae-panel cae-metric p-5 gap-3"):
                    with ui.row().classes(
                        "w-full items-center justify-between"
                    ):
                        ui.label(title).classes("cae-muted text-sm")
                        ui.icon(icon).classes(f"text-{color} text-xl")
                    ui.label(value).classes("text-xl font-bold")

        with ui.row().classes("w-full gap-4 items-stretch"):
            with ui.card().classes(
                "cae-panel p-5 gap-4 flex-1 min-w-72"
            ):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("CAE 세션").classes("font-bold text-lg")
                    ui.badge("메타데이터 기준", color="grey-7").props(
                        "outline"
                    )
                with ui.row().classes("gap-2"):
                    status_badge(
                        "Workbench",
                        active=snapshot.workbench_session,
                        icon="account_tree",
                    )
                    status_badge(
                        "Mechanical",
                        active=snapshot.mechanical_session_count > 0,
                        icon="precision_manufacturing",
                    )
                ui.label(
                    "실제 CAE 작업 전에는 Codex가 CLI ping으로 연결을 다시 "
                    "검증합니다."
                ).classes("cae-muted text-xs")

            with ui.card().classes(
                "cae-panel p-5 gap-3 flex-1 min-w-72"
            ):
                ui.label("다음 작업").classes("font-bold text-lg")
                with ui.row().classes("items-start gap-3 no-wrap"):
                    ui.icon("looks_one").classes("text-primary text-xl")
                    ui.label("입력 파일을 업로드하거나 기존 파일을 확인합니다.")
                with ui.row().classes("items-start gap-3 no-wrap"):
                    ui.icon("looks_two").classes("text-primary text-xl")
                    ui.label("Codex에 원하는 모델링·해석 작업을 요청합니다.")
                with ui.row().classes("items-start gap-3 no-wrap"):
                    ui.icon("looks_3").classes("text-primary text-xl")
                    ui.label("스크립트와 예상 변경을 확인한 뒤 실행을 승인합니다.")

        with ui.card().classes("cae-panel w-full p-5 gap-3"):
            ui.label("환경 진단 상세").classes("font-bold text-lg")
            for check in snapshot.checks:
                color = {
                    "PASS": "positive",
                    "WARN": "accent",
                    "FAIL": "negative",
                }.get(check.status.value, "grey-6")
                icon = {
                    "PASS": "check_circle",
                    "WARN": "warning",
                    "FAIL": "cancel",
                }.get(check.status.value, "help")
                with ui.row().classes("items-start gap-3 no-wrap"):
                    ui.icon(icon).classes(f"text-{color} text-lg mt-0.5")
                    with ui.column().classes("gap-0"):
                        ui.label(
                            f"{check.status.value} · {check.name}"
                        ).classes("text-xs font-bold")
                        ui.label(check.message).classes("cae-muted text-sm")

    upload_feedback: Any
    replacement_summary: Any
    replacement_detail: Any
    replacement_state: dict[str, PendingUploadReplacement | None] = {
        "pending": None
    }
    chat_attachment_chips: Any
    selected_inputs: set[str] = set()
    chat_session = ChatSession()
    # 브라우저 세션마다 대화 문맥과 App Server 프로세스를 분리한다.
    codex_client = CodexAppServerClient(
        Path.cwd(),
        audit_path=config.workspace.logs_dir / "codex-approvals.jsonl",
    )
    pending_approvals: dict[int, ApprovalRequest] = {}
    # 진행 단계는 assistant 메시지 ID별로 보관한다. 메뉴 탭은 같은 페이지의
    # 렌더링만 전환하므로 사용자가 다른 메뉴를 보는 동안에도 이 상태와 Codex
    # 스트림은 유지된다. 브라우저 연결 자체가 끊기면 아래 on_disconnect에서
    # App Server를 종료하므로 새로고침 후까지 영속화하는 용도는 아니다.
    progress_steps: dict[str, dict[str, ChatProgressStep]] = {}
    # 사용자가 탭을 닫으면 해당 브라우저 세션의 자식 프로세스도 종료한다.
    # 테스트용 UI 대역에는 context가 없을 수 있으므로 실제 NiceGUI에서만 등록한다.
    if hasattr(ui, "context") and hasattr(ui.context, "client"):
        ui.context.client.on_disconnect(codex_client.close)
    chat_input: Any
    chat_stream: Any
    chat_uploader: Any
    chat_status: Any
    chat_activity_spinner: Any
    chat_activity_label: Any
    codex_connection_badge: Any
    workbench_connection_badge: Any
    codex_connection_detail: Any
    workbench_connection_detail: Any
    send_button: Any
    stop_button: Any
    retry_button: Any

    def update_progress_step(
        assistant_id: str,
        *,
        step_id: str,
        title: str,
        status: str,
        detail: str,
    ) -> None:
        """동일 App Server 항목의 시작·요약·완료 이벤트를 한 줄로 합친다."""
        message_steps = progress_steps.setdefault(assistant_id, {})
        step = message_steps.get(step_id)
        if step is None:
            step = ChatProgressStep(step_id=step_id, title=title)
            message_steps[step_id] = step
        if title:
            step.title = title
        step.status = status or step.status
        if detail:
            if step.detail and status == "running":
                step.detail = f"{step.detail}{detail}"[-600:]
            else:
                step.detail = detail[-600:]
        if step.status in {"completed", "failed"}:
            step.completed_at = datetime.now(timezone.utc)

    def progress_elapsed_text(step: ChatProgressStep) -> str:
        """진행 중 또는 완료 시점까지의 경과 시간을 짧은 한글 표기로 반환한다."""
        end = step.completed_at or datetime.now(timezone.utc)
        seconds = max(0, int((end - step.started_at).total_seconds()))
        return f"{seconds}초"

    def refresh_progress_clock() -> None:
        """응답 생성 중에만 경과 시간 숫자를 1초 간격으로 다시 그린다."""
        if chat_session.status is ChatStatus.STREAMING:
            chat_messages.refresh()

    def finalize_progress_steps(
        assistant_id: str,
        *,
        final_status: str,
    ) -> None:
        """턴 종료 시 완료 알림이 없던 진행 단계도 화면에 실행 결과를 남긴다."""
        for step in progress_steps.get(assistant_id, {}).values():
            if step.status == "running":
                step.status = final_status
                step.completed_at = datetime.now(timezone.utc)

    async def scroll_chat_to_latest(*, force: bool = False) -> None:
        """새 메시지를 보여주되 사용자가 과거 대화를 읽는 중이면 위치를 보존한다.

        새 질문을 보낸 직후에는 ``force=True``로 항상 맨 아래로 이동한다.
        스트리밍 중에는 현재 하단과의 거리가 220px 이내일 때만 따라가므로,
        사용자가 직접 위로 스크롤해 이전 답변을 읽는 동작을 방해하지 않는다.
        """
        await asyncio.sleep(0)
        force_value = "true" if force else "false"
        await ui.run_javascript(
            """
            const stream = document.getElementById('cae-chat-stream');
            if (!stream) return;
            const isNearBottom = () =>
                stream.scrollHeight - stream.scrollTop -
                stream.clientHeight <= 220;

            // 사용자가 스크롤을 위로 올리면 자동 추적을 멈추고, 다시 하단으로
            // 내려오면 추적을 재개한다. 이 값을 DOM에 보관해야 새 텍스트가
            // 추가되어 scrollHeight가 커져도 직전 사용자의 의도를 잃지 않는다.
            if (!stream.dataset.autoFollowInitialized) {
                stream.dataset.autoFollowInitialized = 'true';
                stream.dataset.autoFollow = isNearBottom() ? 'true' : 'false';
                stream.addEventListener('scroll', () => {
                    stream.dataset.autoFollow =
                        isNearBottom() ? 'true' : 'false';
                }, {passive: true});
            }
            if (FORCE_SCROLL) {
                stream.dataset.autoFollow = 'true';
            }
            if (stream.dataset.autoFollow === 'true') {
                requestAnimationFrame(() => {
                    stream.scrollTo({
                        top: stream.scrollHeight,
                        // 짧은 스트리밍 델타마다 애니메이션을 다시 시작하면
                        // 스크롤이 답변 속도를 따라가지 못하므로 즉시 이동한다.
                        behavior: 'auto',
                    });
                });
            }
            """.replace("FORCE_SCROLL", force_value)
        )

    async def open_chat_file_picker() -> None:
        """숨겨 둔 기본 업로더의 파일 선택 창을 작성기 ``+`` 버튼으로 연다."""
        await chat_uploader.run_method("pickFiles")

    def refresh_codex_connection_badge(*, error: str | None = None) -> None:
        """현재 App Server 프로세스 상태를 Codex 연결 배지에 반영한다."""
        if error is not None:
            codex_connection_badge.set_text("Codex · 연결 오류")
            codex_connection_badge.props("color=negative outline")
            codex_connection_detail.set_text(error)
        elif codex_client.connected:
            codex_connection_badge.set_text("Codex · 연결됨")
            codex_connection_badge.props("color=positive outline")
            codex_connection_detail.set_text(
                "Codex App Server가 localhost stdio로 연결되어 있습니다."
            )
        else:
            codex_connection_badge.set_text("Codex · 미연결")
            codex_connection_badge.props("color=grey-6 outline")
            codex_connection_detail.set_text(
                "첫 메시지를 보내면 Codex App Server에 연결합니다."
            )

    async def refresh_service_connections() -> None:
        """UI를 멈추지 않고 Codex와 Workbench의 실제 연결 상태를 갱신한다."""
        refresh_codex_connection_badge()
        workbench_connection_badge.set_text("Workbench · 확인 중")
        workbench_connection_badge.props("color=accent outline")
        result = await asyncio.to_thread(probe_workbench_connection, config)
        workbench_connection_badge.set_text(result.label)
        workbench_connection_badge.props(
            "color=positive outline"
            if result.connected
            else "color=grey-6 outline"
        )
        workbench_connection_detail.set_text(result.detail)

    def refresh_attachment_selection() -> None:
        """선택된 파일을 다음 채팅 단계가 사용할 첨부 목록으로 표시한다."""
        chat_attachment_chips.clear()
        with chat_attachment_chips:
            if not selected_inputs:
                return
            for name in sorted(selected_inputs):
                kind = classify_attachment(name)
                ui.chip(
                    f"{kind.value} · {name}",
                    icon="image" if kind.value == "이미지" else "attach_file",
                    removable=True,
                    on_value_change=lambda event, filename=name: (
                        set_input_attachment(filename, bool(event.value))
                    ),
                ).props("outline color=primary")

    def set_input_attachment(name: str, selected: bool) -> None:
        """입력 파일 하나를 향후 Codex 채팅 첨부 목록에 추가하거나 제거한다."""
        if selected:
            selected_inputs.add(name)
        else:
            selected_inputs.discard(name)
        refresh_attachment_selection()

    def update_chat_controls() -> None:
        """현재 응답 상태에 맞춰 전송·중지·재시도 버튼을 활성화한다."""
        if chat_session.status is ChatStatus.STREAMING:
            chat_activity_spinner.set_visibility(True)
            chat_activity_label.set_text("Codex가 응답을 생성하고 있습니다")
            chat_activity_label.classes(replace="text-sm text-accent font-medium")
            send_button.disable()
            send_button.set_visibility(False)
            stop_button.enable()
            stop_button.set_visibility(True)
            retry_button.disable()
            retry_button.set_visibility(False)
            chat_status.set_text("Codex가 답변을 생성하고 있습니다.")
            chat_status.classes(replace="text-sm text-accent")
        else:
            chat_activity_spinner.set_visibility(False)
            send_button.enable()
            send_button.set_visibility(True)
            stop_button.disable()
            stop_button.set_visibility(False)
            can_retry = any(
                message.role is MessageRole.USER
                for message in chat_session.messages
            )
            show_retry = can_retry and chat_session.status in {
                ChatStatus.STOPPED,
                ChatStatus.ERROR,
            }
            retry_button.set_visibility(show_retry)
            if show_retry:
                retry_button.enable()
            else:
                retry_button.disable()
            state_text = {
                ChatStatus.IDLE: "메시지를 입력할 수 있습니다.",
                ChatStatus.STOPPED: "응답이 중지되었습니다. 다시 시도할 수 있습니다.",
                ChatStatus.ERROR: "응답에 실패했습니다. 다시 시도할 수 있습니다.",
            }.get(chat_session.status, "메시지를 입력할 수 있습니다.")
            chat_status.set_text(state_text)
            chat_status.classes(
                replace=(
                    "text-sm text-negative"
                    if chat_session.status is ChatStatus.ERROR
                    else "text-sm cae-muted"
                )
            )
            activity_text = {
                ChatStatus.IDLE: "대기 중",
                ChatStatus.STOPPED: "응답 중지됨",
                ChatStatus.ERROR: "응답 오류",
            }.get(chat_session.status, "대기 중")
            chat_activity_label.set_text(activity_text)
            chat_activity_label.classes(
                replace=(
                    "text-sm text-negative font-medium"
                    if chat_session.status is ChatStatus.ERROR
                    else "text-sm cae-muted font-medium"
                )
            )

    def message_role_label(role: MessageRole) -> tuple[str, str, str]:
        """역할별 화면 이름, 아이콘과 카드 CSS 클래스를 반환한다."""
        return {
            MessageRole.USER: ("사용자", "person", "cae-message-user"),
            MessageRole.ASSISTANT: (
                "CAE Agent · Codex",
                "smart_toy",
                "cae-message-assistant",
            ),
            MessageRole.SYSTEM: (
                "시스템",
                "info",
                "cae-message-system",
            ),
            MessageRole.ERROR: (
                "오류",
                "error",
                "cae-message-error",
            ),
        }[role]

    @ui.refreshable
    def chat_messages() -> None:
        """사용자·assistant·시스템·오류 메시지를 역할별 카드로 표시한다."""
        if not chat_session.messages:
            with ui.column().classes(
                "w-full flex-1 items-center justify-center py-16 gap-3"
            ):
                ui.icon("forum").classes("text-primary text-5xl")
                ui.label("첫 CAE 요청을 입력하세요").classes(
                    "text-xl font-bold"
                )
                ui.label(
                    "Codex가 현재 저장소의 문맥을 읽고 답합니다. "
                    "일반 작업은 자동 승인하고 위험한 CAE 실행만 확인받습니다."
                ).classes("cae-muted text-sm text-center max-w-xl")
                ui.label(
                    "예: 선택한 STEP 파일의 형상 검토 계획을 작성해줘"
                ).classes("text-primary text-sm")
            return

        for message in chat_session.messages:
            role_label, role_icon, message_class = message_role_label(
                message.role
            )
            with ui.column().classes(
                f"cae-message {message_class} gap-3"
            ):
                with ui.row().classes(
                    "w-full items-center justify-between gap-3"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(role_icon).classes("text-primary")
                        ui.label(role_label).classes("font-bold text-sm")
                    ui.label(
                        f"{message.created_at:%H:%M}"
                    ).classes("cae-muted text-xs")
                if message.attachments:
                    with ui.row().classes("gap-2 flex-wrap"):
                        for attachment in message.attachments:
                            ui.chip(
                                attachment,
                                icon="attach_file",
                            ).props("dense outline color=primary")
                message_progress = list(
                    progress_steps.get(message.message_id, {}).values()
                )
                if message.role is MessageRole.ASSISTANT and message_progress:
                    completed_count = sum(
                        step.status == "completed"
                        for step in message_progress
                    )
                    is_active = (
                        chat_session.status is ChatStatus.STREAMING
                        and chat_session.active_assistant_id
                        == message.message_id
                    )
                    panel_title = (
                        f"작업 중 · {len(message_progress)}단계"
                        if is_active
                        else (
                            f"작업 과정 · {completed_count}/"
                            f"{len(message_progress)} 완료"
                        )
                    )
                    with ui.expansion(
                        panel_title,
                        icon="progress_activity" if is_active else "task_alt",
                        value=is_active,
                    ).classes("cae-progress-panel w-full"):
                        for step in message_progress:
                            icon = {
                                "running": "progress_activity",
                                "completed": "check_circle",
                                "failed": "error",
                                "stopped": "stop_circle",
                            }.get(step.status, "radio_button_unchecked")
                            color = {
                                "running": "accent",
                                "completed": "positive",
                                "failed": "negative",
                                "stopped": "grey-6",
                            }.get(step.status, "grey-6")
                            with ui.row().classes(
                                "cae-progress-step w-full items-start "
                                "gap-2 no-wrap"
                            ):
                                ui.icon(icon).classes(
                                    f"text-{color} text-base mt-0.5"
                                )
                                with ui.column().classes("flex-1 gap-0"):
                                    ui.label(step.title).classes(
                                        "text-sm font-medium"
                                    )
                                    if step.detail:
                                        ui.label(step.detail).classes(
                                            "cae-progress-detail cae-muted "
                                            "text-xs"
                                        )
                                ui.label(
                                    progress_elapsed_text(step)
                                ).classes("cae-muted text-xs")
                body = message.content
                if (
                    message.role is MessageRole.ASSISTANT
                    and not body
                    and chat_session.status is ChatStatus.STREAMING
                ):
                    body = "응답을 준비하고 있습니다…"
                ui.label(body).classes("cae-message-body text-sm")
                for detail in message.details:
                    detail_icon = {
                        MessageDetailKind.SCRIPT: "code",
                        MessageDetailKind.COMMAND: "terminal",
                        MessageDetailKind.LOG: "article",
                    }[detail.kind]
                    with ui.expansion(
                        detail.title,
                        icon=detail_icon,
                    ).classes("w-full"):
                        ui.code(detail.content).classes("w-full text-xs")

    async def decide_approval(
        request: ApprovalRequest,
        *,
        approved: bool,
    ) -> None:
        """카드에 표시된 동일 승인 요청을 승인하거나 거절한다."""
        try:
            await codex_client.resolve_approval(
                request.request_id,
                request.fingerprint,
                approved=approved,
            )
        except CodexAppServerError as error:
            chat_status.set_text(str(error))
            chat_status.classes(replace="text-sm text-negative")
        else:
            if chat_session.active_assistant_id is not None:
                update_progress_step(
                    chat_session.active_assistant_id,
                    step_id=f"approval-{request.request_id}",
                    title=(
                        "사용자가 작업을 승인했습니다"
                        if approved
                        else "사용자가 작업을 거절했습니다"
                    ),
                    status="completed" if approved else "failed",
                    detail=request.title,
                )
            chat_messages.refresh()
        finally:
            pending_approvals.pop(request.request_id, None)
            approval_cards.refresh()

    @ui.refreshable
    def approval_cards() -> None:
        """Codex가 실제 실행 전에 보낸 승인 요청을 위험도별 카드로 표시한다."""
        for request in pending_approvals.values():
            color = {
                ApprovalRisk.CREATE: "primary",
                ApprovalRisk.ROUTINE: "positive",
                ApprovalRisk.MODIFY: "accent",
                ApprovalRisk.EXECUTE: "warning",
                ApprovalRisk.DELETE: "negative",
            }[request.risk]
            with ui.card().classes(
                "cae-panel cae-danger w-full p-4 gap-3"
            ):
                with ui.row().classes(
                    "w-full items-center justify-between gap-3"
                ):
                    ui.label(request.title).classes("font-bold")
                    ui.badge(request.risk.value, color=color).props("outline")
                ui.label(f"대상: {request.target}").classes("text-sm")
                ui.label(request.reason).classes("cae-muted text-sm")
                with ui.expansion(
                    "명령·변경 미리보기",
                    icon="preview",
                ).classes("w-full"):
                    ui.code(request.preview).classes("w-full text-xs")
                ui.label(
                    "이 승인은 표시된 요청 한 건에만 유효합니다. 대상이나 "
                    "내용이 바뀌면 다시 승인해야 합니다."
                ).classes("cae-muted text-xs")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(
                        "거절",
                        icon="block",
                        on_click=lambda _request=request: decide_approval(
                            _request,
                            approved=False,
                        ),
                    ).props("outline rounded no-caps color=negative")
                    ui.button(
                        "이 작업 승인",
                        icon="verified_user",
                        on_click=lambda _request=request: decide_approval(
                            _request,
                            approved=True,
                        ),
                        color=color,
                    ).props("unelevated rounded no-caps")

    async def stream_codex_message(
        assistant: ChatMessage,
        *,
        prompt: str,
        attachments: tuple[str, ...],
    ) -> None:
        """Codex App Server의 실제 텍스트 이벤트를 화면에 순서대로 누적한다."""
        try:
            codex_connection_badge.set_text("Codex · 연결 중")
            codex_connection_badge.props("color=accent outline")
            attachment_paths = tuple(
                config.workspace.input_dir / name for name in attachments
            )
            async for event in codex_client.stream_turn(
                prompt,
                attachments=attachment_paths,
            ):
                if chat_session.status is not ChatStatus.STREAMING:
                    return
                if event.kind == "delta":
                    refresh_codex_connection_badge()
                    chat_session.append_stream(
                        assistant.message_id,
                        event.text,
                    )
                    chat_messages.refresh()
                    await scroll_chat_to_latest()
                elif event.kind == "progress":
                    update_progress_step(
                        assistant.message_id,
                        step_id=event.item_id or "codex-progress",
                        title=event.title or "작업을 진행하고 있습니다",
                        status=event.status or "running",
                        detail=event.detail,
                    )
                    chat_messages.refresh()
                    await scroll_chat_to_latest()
                elif event.kind == "approval" and event.approval is not None:
                    update_progress_step(
                        assistant.message_id,
                        step_id=f"approval-{event.approval.request_id}",
                        title="작업 승인을 확인하고 있습니다",
                        status="running",
                        detail=event.approval.title,
                    )
                    if requires_manual_approval(event.approval):
                        pending_approvals[event.approval.request_id] = (
                            event.approval
                        )
                        approval_cards.refresh()
                        await scroll_chat_to_latest()
                        chat_status.set_text(
                            "위험 작업이 사용자 승인을 기다리고 있습니다."
                        )
                        chat_status.classes(replace="text-sm text-accent")
                    else:
                        await codex_client.resolve_approval(
                            event.approval.request_id,
                            event.approval.fingerprint,
                            approved=True,
                            automatic=True,
                        )
                        update_progress_step(
                            assistant.message_id,
                            step_id=f"approval-{event.approval.request_id}",
                            title="안전 정책으로 승인했습니다",
                            status="completed",
                            detail=event.approval.title,
                        )
                        chat_status.set_text(
                            f"{event.approval.risk.value}을 안전 정책으로 "
                            "자동 승인했습니다."
                        )
                        chat_status.classes(replace="text-sm text-positive")
                    chat_messages.refresh()
            chat_session.complete(
                assistant.message_id,
                details=(
                    MessageDetail(
                        kind=MessageDetailKind.COMMAND,
                        title="현재 안전 모드",
                        content=(
                            "Codex App Server 연결됨\n"
                            "작업공간 쓰기: 사용자 승인 필요\n"
                            "명령·파일 변경: 일회성 승인\n"
                            "광범위 권한 요청: 자동 거절"
                        ),
                    ),
                    MessageDetail(
                        kind=MessageDetailKind.LOG,
                        title="Codex 연결 정보",
                        content=(
                            f"thread: {codex_client.thread_id}\n"
                            f"turn: {codex_client.turn_id}\n"
                            "transport: local stdio JSONL"
                        ),
                    ),
                ),
            )
            finalize_progress_steps(
                assistant.message_id,
                final_status="completed",
            )
        except (ChatError, CodexAppServerError) as error:
            refresh_codex_connection_badge(error=str(error))
            finalize_progress_steps(
                assistant.message_id,
                final_status="failed",
            )
            if chat_session.status is ChatStatus.STREAMING:
                chat_session.fail(assistant.message_id, str(error))
        finally:
            chat_messages.refresh()
            update_chat_controls()
            await scroll_chat_to_latest()

    async def send_chat_message() -> None:
        """입력값과 선택 첨부를 실제 Codex 대화 스레드로 전송한다."""
        prompt = str(chat_input.value or "")
        attachments = tuple(sorted(selected_inputs))
        try:
            assistant = chat_session.submit(
                prompt,
                attachments=attachments,
            )
        except ChatError as error:
            chat_status.set_text(str(error))
            chat_status.classes(replace="text-sm text-negative")
            return

        chat_input.value = ""
        progress_steps[assistant.message_id] = {
            "turn": ChatProgressStep(
                step_id="turn",
                title="Codex 요청을 시작하고 있습니다",
            )
        }
        # 첨부는 일반 채팅 앱처럼 현재 메시지에만 사용한다. 재시도에 필요한
        # 파일명은 이미 ChatMessage에 복사됐으므로 선택 목록만 안전하게 비운다.
        selected_inputs.clear()
        refresh_attachment_selection()
        chat_messages.refresh()
        update_chat_controls()
        await scroll_chat_to_latest(force=True)
        await stream_codex_message(
            assistant,
            prompt=prompt,
            attachments=attachments,
        )

    async def stop_chat_message() -> None:
        """현재 Codex 턴을 중단하고 이미 받은 응답 텍스트는 보존한다."""
        try:
            await codex_client.interrupt()
            chat_session.stop()
            finalize_progress_steps(
                assistant_id=chat_session.messages[-1].message_id,
                final_status="stopped",
            )
        except (ChatError, CodexAppServerError) as error:
            chat_status.set_text(str(error))
            chat_status.classes(replace="text-sm text-negative")
        chat_messages.refresh()
        update_chat_controls()

    async def retry_chat_message() -> None:
        """마지막 사용자 요청과 첨부를 같은 Codex 스레드에서 다시 실행한다."""
        try:
            assistant = chat_session.retry_last()
        except ChatError as error:
            chat_status.set_text(str(error))
            chat_status.classes(replace="text-sm text-negative")
            return
        progress_steps[assistant.message_id] = {
            "turn": ChatProgressStep(
                step_id="turn",
                title="마지막 요청을 다시 시작하고 있습니다",
            )
        }
        user_message = chat_session.messages[-2]
        chat_messages.refresh()
        update_chat_controls()
        await scroll_chat_to_latest(force=True)
        await stream_codex_message(
            assistant,
            prompt=user_message.content,
            attachments=user_message.attachments,
        )

    @ui.refreshable
    def activity_content() -> None:
        """최근 로그와 결과를 서로 구분해 읽기 전용으로 표시한다."""
        try:
            snapshot = dashboard_snapshot(config)
        except (OSError, WorkspaceError) as error:
            ui.label(f"활동 조회 실패: {error}").classes("text-negative")
            return
        with ui.row().classes("w-full gap-4 items-stretch"):
            with ui.card().classes(
                "cae-panel flex-1 min-w-72 p-5 gap-2"
            ):
                ui.label("최근 로그").classes("font-bold text-lg")
                file_list(
                    snapshot.recent_logs,
                    empty_text="저장된 실행 로그가 없습니다.",
                    icon="article",
                )
            with ui.card().classes(
                "cae-panel flex-1 min-w-72 p-5 gap-2"
            ):
                ui.label("최근 결과").classes("font-bold text-lg")
                file_list(
                    snapshot.recent_results,
                    empty_text="저장된 CAE 결과가 없습니다.",
                    icon="analytics",
                )

    async def handle_upload(event: Any) -> None:
        """NiceGUI 임시 업로드를 읽어 검증된 입력 파일로 저장한다."""
        try:
            content = await event.file.read()
            stored = store_input_upload(
                config,
                filename=event.file.name,
                content=content,
            )
        except UploadConflict as conflict:
            pending = conflict.pending
            if replacement_state["pending"] is not None:
                upload_feedback.set_text(
                    "먼저 열려 있는 파일 교체 경고를 처리한 뒤 다시 업로드하세요."
                )
                upload_feedback.classes(replace="text-sm text-negative")
                return
            replacement_state["pending"] = pending
            replacement_summary.set_text(
                f"`{pending.target.name}` 파일이 이미 있습니다."
            )
            replacement_detail.set_text(
                f"기존 {_format_bytes(pending.original_size)} → "
                f"새 파일 {_format_bytes(len(pending.content))}"
            )
            replacement_dialog.open()
            upload_feedback.set_text(
                "중복 파일 교체 여부를 경고 모달에서 확인하세요."
            )
            upload_feedback.classes(replace="text-sm text-accent")
        except (OSError, UIError) as error:
            upload_feedback.set_text(f"업로드 실패: {error}")
            upload_feedback.classes(replace="text-sm text-negative")
        else:
            selected_inputs.add(stored.path.name)
            kind = classify_attachment(stored.path)
            upload_feedback.set_text(
                f"첨부 완료: {kind.value} · {stored.path.name} · "
                f"{_format_bytes(stored.size_bytes)} · "
                "다음 메시지에 전달됩니다."
            )
            upload_feedback.classes(replace="text-sm text-positive")
            overview_content.refresh()
        refresh_attachment_selection()

    def cancel_upload_replacement() -> None:
        """중복 업로드 내용을 버리고 기존 입력 파일을 그대로 유지한다."""
        replacement_state["pending"] = None
        replacement_dialog.close()
        upload_feedback.set_text("파일 교체를 취소했습니다. 기존 파일은 유지됩니다.")
        upload_feedback.classes(replace="text-sm cae-muted")

    def approve_upload_replacement() -> None:
        """모달에서 확인한 기존 파일이 그대로일 때만 교체를 실행한다."""
        pending = replacement_state["pending"]
        if pending is None:
            upload_feedback.set_text("승인할 중복 업로드가 없습니다.")
            upload_feedback.classes(replace="text-sm text-negative")
            replacement_dialog.close()
            return
        try:
            stored = replace_input_upload(config, pending)
        except (OSError, UIError) as error:
            upload_feedback.set_text(f"파일 교체 실패: {error}")
            upload_feedback.classes(replace="text-sm text-negative")
        else:
            selected_inputs.add(stored.path.name)
            kind = classify_attachment(stored.path)
            upload_feedback.set_text(
                f"교체 완료: {kind.value} · {stored.path.name} · "
                f"{_format_bytes(stored.size_bytes)}"
            )
            upload_feedback.classes(replace="text-sm text-positive")
            replacement_state["pending"] = None
            replacement_dialog.close()
            overview_content.refresh()
            refresh_attachment_selection()

    feedback: Any
    retention: Any
    candidate_box: Any
    approval_summary: Any

    def execute_cleanup() -> None:
        """직전 미리보기와 후보가 같을 때만 승인된 실제 정리를 실행한다."""
        days = int(cleanup_state["days"] or 30)
        preview = cleanup_state["preview"]
        try:
            current_preview = clean_workspace(
                config,
                older_than_days=days,
                approve=False,
            )
            preview_paths = (
                tuple(item.path for item in preview.candidates)
                if isinstance(preview, CleanupResult)
                else ()
            )
            current_paths = tuple(
                item.path for item in current_preview.candidates
            )
            if preview_paths != current_paths:
                raise WorkspaceError(
                    "미리보기 이후 삭제 후보가 변경되었습니다. "
                    "후보를 다시 확인한 뒤 승인하세요."
                )
            result = clean_workspace(
                config,
                older_than_days=days,
                approve=True,
            )
        except (OSError, WorkspaceError) as error:
            feedback.set_text(f"정리 차단 또는 실패: {error}")
            feedback.classes(replace="text-sm text-negative")
        else:
            feedback.set_text(
                f"정리 완료: {len(result.deleted)}개, "
                f"{_format_bytes(result.deleted_size_bytes)} / "
                f"실패 {len(result.failures)}개 / "
                f"감사 로그 {result.audit_log}"
            )
            feedback.classes(
                replace=(
                    "text-sm text-positive"
                    if not result.failures
                    else "text-sm text-accent"
                )
            )
            overview_content.refresh()
        finally:
            approval_dialog.close()

    def preview_cleanup() -> None:
        """사용자 승인 전에 삭제되지 않는 정리 후보만 계산해 표시한다."""
        try:
            # 브라우저의 number 입력 제한은 개발자 도구나 직접 요청으로 우회할
            # 수 있으므로 서버에서도 보존 기간을 0일 이상으로 다시 제한한다.
            days = max(0, int(retention.value))
            result = clean_workspace(
                config,
                older_than_days=days,
                approve=False,
            )
        except (TypeError, ValueError, OSError, WorkspaceError) as error:
            feedback.set_text(f"정리 후보 계산 실패: {error}")
            feedback.classes(replace="text-sm text-negative")
            return

        cleanup_state["preview"] = result
        cleanup_state["days"] = days
        candidate_box.clear()
        with candidate_box:
            if not result.candidates:
                ui.label("삭제 후보가 없습니다.").classes(
                    "cae-muted text-sm"
                )
            for candidate in result.candidates:
                with ui.row().classes(
                    "cae-file-row w-full items-center justify-between"
                ):
                    ui.label(
                        f"{candidate.category} · "
                        f"{Path(candidate.path).name}"
                    ).classes("text-sm")
                    ui.label(
                        _format_bytes(candidate.size_bytes)
                    ).classes("cae-muted text-xs")
        feedback.set_text(
            f"DRY-RUN: {len(result.candidates)}개, "
            f"{_format_bytes(result.candidate_size_bytes)}. "
            "아직 삭제하지 않았습니다."
        )
        feedback.classes(replace="text-sm text-accent")
        approval_summary.set_text(
            f"{days}일이 지난 후보 {len(result.candidates)}개, "
            f"{_format_bytes(result.candidate_size_bytes)}를 삭제합니다."
        )
        if result.candidates:
            approval_dialog.open()

    with ui.tab_panels(
        navigation,
        value=overview_tab,
        animated=False,
    ).classes("w-full") as panels:
        with ui.tab_panel(overview_tab):
            with ui.column().classes(
                "cae-page w-full max-w-7xl mx-auto p-4 md:p-7 gap-5"
            ):
                section_heading(
                    "OVERVIEW",
                    "CAE 작업공간 개요",
                    "환경과 세션을 확인하고 다음 작업으로 이동합니다.",
                )
                overview_content()

        with ui.tab_panel(chat_tab):
            with ui.column().classes(
                "cae-chat-page w-full max-w-[1600px] mx-auto p-3 md:p-5 gap-3"
            ):
                with ui.row().classes(
                    "cae-chat-statusbar w-full items-center justify-between "
                    "gap-3 px-4 rounded-2xl"
                ):
                    with ui.row().classes(
                        "items-center gap-3 min-w-0"
                    ):
                        chat_activity_spinner = ui.spinner(
                            size="20px",
                            color="accent",
                        )
                        chat_activity_label = ui.label("대기 중").classes(
                            "text-sm cae-muted font-medium"
                        )
                        ui.separator().props("vertical").classes("h-5 opacity-30")
                        codex_connection_badge = ui.badge(
                            "Codex · 미연결",
                            color="grey-6",
                        ).props("outline")
                        workbench_connection_badge = ui.badge(
                            "Workbench · 확인 전",
                            color="grey-6",
                        ).props("outline")
                        ui.badge("안전 작업 자동 승인", color="positive").props(
                            "outline"
                        )
                    ui.button(
                        icon="refresh",
                        on_click=refresh_service_connections,
                    ).props("flat dense round").tooltip("연결 상태 새로고침")
                    codex_connection_detail = ui.label(
                        "첫 메시지를 보내면 Codex에 연결합니다."
                    ).classes("hidden")
                    workbench_connection_detail = ui.label(
                        "Workbench 연결을 확인합니다."
                    ).classes("hidden")
                    ui.timer(
                        0.1,
                        refresh_service_connections,
                        once=True,
                    )

                with ui.column().classes("cae-chat-shell w-full gap-0"):
                    chat_stream = ui.column().classes(
                        "cae-chat-stream w-full gap-4"
                    ).props("id=cae-chat-stream")
                    with chat_stream:
                        chat_messages()
                        approval_cards()

                    with ui.card().classes(
                        "cae-composer cae-panel w-full px-4 pt-5 pb-3 gap-1"
                    ):
                        chat_uploader = ui.upload(
                            on_upload=handle_upload,
                            on_rejected=lambda: upload_feedback.set_text(
                                "첨부 거부: 지원 형식과 파일 크기를 확인해 주세요."
                            ),
                            multiple=True,
                            auto_upload=True,
                            max_file_size=MAX_UPLOAD_SIZE_BYTES,
                            max_files=10,
                            max_total_size=500 * 1024 * 1024,
                        ).props(
                            'accept=".png,.jpg,.jpeg,.webp,.bmp,.step,.stp,'
                            '.iges,.igs,.scdoc,.wbpj,.mechdat,.csv,.json,.txt" '
                            "flat"
                        ).classes("cae-hidden-upload")
                        with ui.column().classes(
                            "cae-composer-inner gap-1"
                        ):
                            chat_attachment_chips = ui.row().classes(
                                "w-full gap-1 flex-wrap px-1"
                            )
                            chat_input = ui.textarea(
                                placeholder="CAE 작업을 자연어로 입력하세요",
                            ).props(
                                "borderless autogrow rows=1 maxlength=4000"
                            ).classes("cae-chat-input w-full")
                            with ui.row().classes(
                                "cae-composer-actions w-full items-center "
                                "justify-between gap-2"
                            ):
                                with ui.row().classes("items-center gap-1"):
                                    ui.button(
                                        icon="add",
                                        on_click=open_chat_file_picker,
                                    ).props(
                                        "flat dense round color=grey-4"
                                    ).tooltip("파일 첨부")
                                    retry_button = ui.button(
                                        icon="replay",
                                        on_click=retry_chat_message,
                                    ).props(
                                        "flat dense round color=grey-4"
                                    ).tooltip("마지막 요청 다시 시도")
                                with ui.row().classes("items-center gap-1"):
                                    stop_button = ui.button(
                                        icon="stop",
                                        on_click=stop_chat_message,
                                        color="negative",
                                    ).props(
                                        "unelevated dense round"
                                    ).tooltip("응답 중지")
                                    send_button = ui.button(
                                        icon="arrow_upward",
                                        on_click=send_chat_message,
                                    ).props(
                                        "unelevated dense round"
                                    ).tooltip("전송")
                        upload_feedback = ui.label("").classes(
                            "cae-composer-feedback text-xs text-center "
                            "w-full max-w-4xl mx-auto"
                        )
                        # 기존 상태 갱신 코드는 유지하되 중복 안내 문구는 화면에서
                        # 숨긴다. 생성 상태는 상단 상태 표시줄에서 한 번만 보여준다.
                        chat_status = ui.label("").classes("hidden")
                        update_chat_controls()
                        ui.timer(1.0, refresh_progress_clock)

        with ui.tab_panel(activity_tab):
            with ui.column().classes(
                "cae-page w-full max-w-7xl mx-auto p-4 md:p-7 gap-5"
            ):
                section_heading(
                    "ACTIVITY",
                    "로그와 결과",
                    "최근 실행 기록과 결과 파일을 작업공간 기준으로 확인합니다.",
                )
                with ui.row().classes("justify-end"):
                    ui.button(
                        "새로고침",
                        icon="refresh",
                        on_click=activity_content.refresh,
                    ).props("outline rounded no-caps")
                activity_content()

        with ui.tab_panel(maintenance_tab):
            with ui.column().classes(
                "cae-page w-full max-w-7xl mx-auto p-4 md:p-7 gap-5"
            ):
                section_heading(
                    "MAINTENANCE",
                    "작업공간 유지관리",
                    "정리 미리보기는 파일을 삭제하지 않습니다. 실제 정리는 "
                    "별도 승인과 후보 재검증을 거칩니다.",
                )
                with ui.card().classes(
                    "cae-panel cae-danger w-full p-5 md:p-7 gap-4"
                ):
                    with ui.row().classes("items-center gap-3"):
                        ui.icon("delete_sweep").classes(
                            "text-negative text-2xl"
                        )
                        with ui.column().classes("gap-0"):
                            ui.label("오래된 임시 파일 정리").classes(
                                "font-bold text-lg"
                            )
                            ui.label(
                                "input과 results는 자동 정리 대상이 아닙니다."
                            ).classes("cae-muted text-sm")
                    retention = ui.number(
                        label="보존 기간(일)",
                        value=30,
                        min=0,
                        step=1,
                    ).classes("w-48")
                    candidate_box = ui.column().classes(
                        "w-full max-h-72 overflow-auto rounded-lg "
                        "border border-slate-700 p-3"
                    )
                    feedback = ui.label(
                        "먼저 정리 후보 미리보기를 실행하세요."
                    ).classes("cae-muted text-sm")
                    ui.button(
                        "정리 후보 미리보기",
                        icon="preview",
                        on_click=preview_cleanup,
                        color="negative",
                    ).props("outline rounded no-caps")

    with ui.dialog() as approval_dialog, ui.card().classes(
        "cae-dialog-card cae-danger min-w-96 max-w-xl p-6 gap-4"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("warning").classes("text-negative text-3xl")
            ui.label("작업공간 파일 삭제 승인").classes(
                "font-bold text-xl"
            )
        approval_summary = ui.label()
        ui.label(
            "generated, logs와 Codex 임시 파일만 대상입니다. "
            "input과 results는 삭제하지 않습니다."
        ).classes("cae-muted text-sm")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button(
                "취소",
                on_click=approval_dialog.close,
            ).props("flat rounded no-caps")
            ui.button(
                "삭제 승인",
                on_click=execute_cleanup,
                color="negative",
            ).props("unelevated rounded no-caps")

    with ui.dialog() as replacement_dialog, ui.card().classes(
        "cae-dialog-card cae-danger min-w-96 max-w-xl p-6 gap-4"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("warning").classes("text-accent text-3xl")
            ui.label("기존 입력 파일 교체").classes("font-bold text-xl")
        replacement_summary = ui.label().classes("font-medium")
        replacement_detail = ui.label().classes("cae-muted text-sm")
        ui.label(
            "교체하면 같은 이름의 기존 파일 내용이 사라집니다. 승인 직전에 "
            "기존 파일의 크기와 수정 시각을 다시 확인하며, 달라졌다면 교체하지 "
            "않습니다."
        ).classes("cae-muted text-sm")
        with ui.row().classes("justify-end w-full gap-2"):
            ui.button(
                "기존 파일 유지",
                on_click=cancel_upload_replacement,
            ).props("flat rounded no-caps")
            ui.button(
                "파일 교체 승인",
                icon="published_with_changes",
                on_click=approve_upload_replacement,
                color="negative",
            ).props("unelevated rounded no-caps")

    # 탭 패널 객체를 명시적으로 유지해 NiceGUI 클라이언트 수명 동안 삭제되지
    # 않게 한다. 값 자체는 사용하지 않지만 구조의 의도를 코드에 남긴다.
    _ = panels


def launch_ui(
    config: AppConfig,
    *,
    port: int = 8765,
    show: bool = True,
    ui_module: Any | None = None,
) -> None:
    """NiceGUI를 지연 import하고 localhost 전용 대시보드를 시작한다."""
    if not 1 <= port <= 65535:
        raise UIError("UI 포트는 1~65535 범위여야 합니다.")

    active_ui = ui_module
    if active_ui is None:
        try:
            from nicegui import ui as active_ui
        except ImportError as error:
            raise UIError(
                "NiceGUI가 설치되지 않았습니다. "
                '`python -m pip install -e ".[ui]"` 또는 '
                "`setup.ps1 -WithUI`를 실행하세요."
            ) from error

    # NiceGUI 3의 패키지 진입점에서는 실행 스크립트를 다시 불러오는 script mode를
    # 사용할 수 없다. root 함수를 명시하면 브라우저 연결마다 안전하게 화면을
    # 구성하면서 console script와 ``python -m`` 실행을 모두 지원할 수 있다.
    def root() -> None:
        build_dashboard(config, ui_module=active_ui)

    active_ui.run(
        root=root,
        host="127.0.0.1",
        port=port,
        show=show,
        reload=False,
        title="CAE Agent",
    )
