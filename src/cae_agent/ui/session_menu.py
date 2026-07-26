"""채팅 공간을 차지하지 않는 서비스 연결 및 승인 모드 메뉴를 구성한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class SessionMenuControls:
    """채팅 상태 갱신 함수가 조작할 메뉴 내부 UI 요소를 묶어 반환한다."""

    codex_badge: Any
    codex_detail: Any
    workbench_badge: Any
    workbench_detail: Any
    approval_mode_badge: Any


def build_session_menu(
    ui: Any,
    *,
    refresh_connections: Callable[..., Any],
    change_approval_mode: Callable[..., Any],
) -> SessionMenuControls:
    """연결 정보와 YOLO 스위치를 화면 우측 상단의 접이식 메뉴에 등록한다."""
    with ui.button(icon="hub").props(
        "flat dense round aria-label='서비스 연결 상태'"
    ).classes("cae-session-menu-trigger"):
        with ui.menu().classes("cae-session-menu p-3"):
            ui.label("서비스 연결").classes("font-semibold text-sm px-2 pb-1")
            with ui.column().classes("gap-2 min-w-64"):
                codex_badge = ui.badge(
                    "Codex · 미연결",
                    color="grey-6",
                ).props("outline")
                codex_detail = ui.label(
                    "첫 메시지를 보내면 Codex에 연결합니다."
                ).classes("cae-muted text-xs px-1")
                workbench_badge = ui.badge(
                    "Workbench · 확인 전",
                    color="grey-6",
                ).props("outline")
                workbench_detail = ui.label(
                    "Workbench 연결을 확인합니다."
                ).classes("cae-muted text-xs px-1")
                approval_mode_badge = ui.badge(
                    "확인 모드",
                    color="positive",
                ).props("outline")
                ui.switch(
                    "YOLO 모드",
                    value=False,
                    on_change=change_approval_mode,
                ).props("color=negative").tooltip(
                    "켜면 이 브라우저 세션의 실행·삭제 요청을 모두 자동 "
                    "승인합니다. 보호된 파일 경로는 계속 차단합니다."
                )
                ui.label(
                    "YOLO는 실행·삭제 확인을 생략합니다. 새로고침하면 "
                    "확인 모드로 돌아옵니다."
                ).classes("cae-muted text-xs px-1")
                ui.button(
                    "연결 상태 새로고침",
                    icon="refresh",
                    on_click=refresh_connections,
                ).props("flat dense no-caps").classes("self-end")
            ui.timer(0.1, refresh_connections, once=True)
    return SessionMenuControls(
        codex_badge=codex_badge,
        codex_detail=codex_detail,
        workbench_badge=workbench_badge,
        workbench_detail=workbench_detail,
        approval_mode_badge=approval_mode_badge,
    )
