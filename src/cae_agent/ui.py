"""CAE Agent의 읽기 중심 로컬 NiceGUI 대시보드를 구성한다.

UI는 기존 서비스 계층을 직접 호출하며 셸 명령의 텍스트 출력을 다시 파싱하지
않는다. 화면을 열거나 새로고침하는 동작은 진단과 상태 조회만 수행하고, 실제
파일 정리는 dry-run 결과를 표시한 뒤 별도 확인 대화상자에서 승인해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable

from cae_agent.config import AppConfig, prepare_workspace
from cae_agent.doctor import CheckResult, run_checks
from cae_agent.workbench import workbench_paths
from cae_agent.workspace import (
    CleanupResult,
    WorkspaceError,
    WorkspaceStatus,
    clean_workspace,
    workspace_status,
)


class UIError(RuntimeError):
    """로컬 대시보드를 안전하게 구성하거나 시작할 수 없을 때의 오류."""


ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {
        ".csv",
        ".iges",
        ".igs",
        ".json",
        ".mechdat",
        ".scdoc",
        ".step",
        ".stp",
        ".txt",
        ".wbpj",
    }
)
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
class DashboardSnapshot:
    """한 번의 새로고침에서 일관되게 표시할 대시보드 상태."""

    checks: tuple[CheckResult, ...]
    workspace: WorkspaceStatus
    workbench_session: bool
    mechanical_session_count: int
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


def build_dashboard(config: AppConfig, *, ui_module: Any) -> None:
    """주입된 NiceGUI 모듈에 로컬 상태·승인 대시보드를 등록한다."""
    ui = ui_module
    ui.colors(
        primary="#1f4e79",
        secondary="#2f6f73",
        accent="#d97706",
        positive="#15803d",
        negative="#b91c1c",
    )

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("CAE Agent").classes("text-xl font-bold")
        ui.label("Local CAE control dashboard").classes("text-sm opacity-80")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        ui.label("Codex가 자연어 작업을 조정하고, 이 화면은 상태·승인·결과를 확인합니다.") \
            .classes("text-lg")
        ui.label(
            "localhost 전용 · 화면 조회는 Ansys 모델을 변경하지 않음 · "
            "input/results 자동 삭제 금지"
        ).classes("text-sm text-grey-7")

        feedback = ui.label("상태를 불러오는 중입니다.").classes(
            "text-sm text-grey-7"
        )
        cleanup_state: dict[str, CleanupResult | int | None] = {
            "preview": None,
            "days": 30,
        }

        @ui.refreshable
        def dashboard_content() -> None:
            try:
                snapshot = dashboard_snapshot(config)
            except (OSError, WorkspaceError) as error:
                ui.label(f"상태 조회 실패: {error}").classes("text-negative")
                return

            with ui.row().classes("w-full gap-4"):
                with ui.card().classes("min-w-64"):
                    ui.label("환경 진단").classes("font-bold text-lg")
                    for check in snapshot.checks:
                        color = {
                            "PASS": "text-positive",
                            "WARN": "text-accent",
                            "FAIL": "text-negative",
                        }.get(check.status.value, "text-grey-8")
                        ui.label(
                            f"[{check.status.value}] {check.message}"
                        ).classes(f"text-sm {color}")

                with ui.card().classes("min-w-64"):
                    ui.label("세션").classes("font-bold text-lg")
                    workbench_text = (
                        "메타데이터 있음"
                        if snapshot.workbench_session
                        else "세션 없음"
                    )
                    ui.label(f"Workbench: {workbench_text}")
                    ui.label(
                        "Mechanical 메타데이터: "
                        f"{snapshot.mechanical_session_count}개"
                    )
                    ui.label(
                        "세션 파일은 연결 가능성을 나타내며 실제 ping 결과와 "
                        "다를 수 있습니다."
                    ).classes("text-xs text-grey-7")

            ui.label("작업공간").classes("font-bold text-xl mt-2")
            with ui.row().classes("w-full gap-3"):
                for item in snapshot.workspace.directories:
                    with ui.card().classes("min-w-40"):
                        ui.label(item.name).classes("font-bold")
                        ui.label(f"파일 {item.file_count}개")
                        ui.label(_format_bytes(item.size_bytes))
            ui.label(
                "전체 "
                f"{snapshot.workspace.total_file_count}개 / "
                f"{_format_bytes(snapshot.workspace.total_size_bytes)}"
            ).classes("text-sm")

            with ui.row().classes("w-full gap-4"):
                with ui.card().classes("min-w-80"):
                    ui.label("최근 로그").classes("font-bold")
                    if snapshot.recent_logs:
                        for name in snapshot.recent_logs:
                            ui.label(name).classes("text-sm")
                    else:
                        ui.label("로그 없음").classes("text-sm text-grey-7")
                with ui.card().classes("min-w-80"):
                    ui.label("최근 결과").classes("font-bold")
                    if snapshot.recent_results:
                        for name in snapshot.recent_results:
                            ui.label(name).classes("text-sm")
                    else:
                        ui.label("결과 없음").classes("text-sm text-grey-7")

        retention = ui.number(
            label="보존 기간(일)",
            value=30,
            min=0,
            step=1,
        ).classes("w-48")
        candidate_box = ui.column().classes(
            "w-full max-h-72 overflow-auto border rounded p-3"
        )

        ui.separator().classes("my-2")
        ui.label("CAE 입력 파일").classes("font-bold text-xl")
        ui.label(
            "파일은 workspace/input에만 저장됩니다. 업로드만으로 Ansys를 "
            "실행하거나 기존 모델을 변경하지 않습니다."
        ).classes("text-sm text-grey-7")
        upload_feedback = ui.label(
            "STEP, IGES, SpaceClaim, Workbench, Mechanical, CSV, JSON, "
            "TXT 파일을 최대 100 MiB까지 업로드할 수 있습니다."
        ).classes("text-sm text-grey-7")

        async def handle_upload(event: Any) -> None:
            """NiceGUI 임시 업로드를 읽어 검증된 입력 파일로 저장한다."""
            try:
                content = await event.file.read()
                stored = store_input_upload(
                    config,
                    filename=event.file.name,
                    content=content,
                )
            except (OSError, UIError) as error:
                upload_feedback.set_text(f"업로드 실패: {error}")
                upload_feedback.classes(replace="text-sm text-negative")
            else:
                upload_feedback.set_text(
                    f"업로드 완료: {stored.path.name} · "
                    f"{_format_bytes(stored.size_bytes)} · "
                    "이 파일을 사용할 CAE 작업은 Codex에 별도로 요청하세요."
                )
                upload_feedback.classes(replace="text-sm text-positive")
                dashboard_content.refresh()

        ui.upload(
            label="CAE 입력 파일 선택",
            on_upload=handle_upload,
            on_rejected=lambda: upload_feedback.set_text(
                "업로드 거부: 파일 하나당 최대 100 MiB까지 선택할 수 있습니다."
            ),
            multiple=False,
            auto_upload=True,
            max_file_size=MAX_UPLOAD_SIZE_BYTES,
        ).props(
            'accept=".step,.stp,.iges,.igs,.scdoc,.wbpj,.mechdat,'
            '.csv,.json,.txt"'
        ).classes("w-full max-w-2xl")

        with ui.dialog() as approval_dialog, ui.card().classes("min-w-96"):
            ui.label("작업공간 파일 삭제 승인").classes(
                "font-bold text-lg text-negative"
            )
            approval_summary = ui.label()
            ui.label(
                "generated, logs와 Codex 임시 파일만 대상입니다. "
                "input과 results는 삭제하지 않습니다."
            ).classes("text-sm")

            def execute_cleanup() -> None:
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
                    dashboard_content.refresh()
                finally:
                    approval_dialog.close()

            with ui.row().classes("justify-end w-full"):
                ui.button("취소", on_click=approval_dialog.close).props("flat")
                ui.button(
                    "삭제 승인",
                    on_click=execute_cleanup,
                    color="negative",
                )

        def preview_cleanup() -> None:
            try:
                days = int(retention.value)
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
                        "text-sm text-grey-7"
                    )
                for candidate in result.candidates:
                    ui.label(
                        f"[{candidate.category}] {Path(candidate.path).name} · "
                        f"{_format_bytes(candidate.size_bytes)}"
                    ).classes("text-sm")
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

        with ui.row().classes("gap-3"):
            ui.button("상태 새로고침", on_click=dashboard_content.refresh)
            ui.button(
                "정리 후보 미리보기",
                on_click=preview_cleanup,
                color="secondary",
            )

        dashboard_content()


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
