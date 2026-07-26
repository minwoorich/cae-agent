"""CAE Agent의 읽기 중심 로컬 NiceGUI 대시보드를 구성한다.

UI는 기존 서비스 계층을 직접 호출하며 셸 명령의 텍스트 출력을 다시 파싱하지
않는다. 화면을 열거나 새로고침하는 동작은 진단과 상태 조회만 수행하고, 실제
파일 정리는 dry-run 결과를 표시한 뒤 별도 확인 대화상자에서 승인해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cae_agent.config import AppConfig
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
    clean_workspace,
)
from cae_agent.ui_chat import build_chat_panel
from cae_agent.ui_files import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_SIZE_BYTES,
    DashboardSnapshot,
    InputFileSummary,
    PendingUploadReplacement,
    StoredUpload,
    UIError,
    UploadConflict,
    dashboard_snapshot,
    format_bytes as _format_bytes,
    input_file_summaries,
    replace_input_upload,
    store_input_upload,
)
from cae_agent.ui_styles import apply_ui_theme


@dataclass(frozen=True, slots=True)
class ServiceConnection:
    """UI에 표시할 로컬 서비스의 실제 연결 확인 결과."""

    connected: bool
    label: str
    detail: str


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


def build_dashboard(config: AppConfig, *, ui_module: Any) -> None:
    """주입된 NiceGUI 모듈에 구조화된 로컬 CAE 대시보드를 등록한다.

    화면은 개요, 입력 파일, 활동과 유지관리로 분리한다. 현재 단계에서는
    대화 기능을 구현한 것처럼 보이지 않도록 다음 단계임을 명확히 알리고,
    사용자가 가장 먼저 필요한 업로드와 환경 상태에 빠르게 접근하게 한다.
    """
    ui = ui_module
    apply_ui_theme(ui)

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

        build_chat_panel(
            ui,
            config,
            chat_tab,
            overview_content.refresh,
            probe_workbench_connection,
        )

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
