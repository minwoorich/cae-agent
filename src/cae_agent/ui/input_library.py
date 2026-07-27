"""채팅 작성기 안에서 입력 파일 선택과 삭제 UI를 렌더링한다."""

from __future__ import annotations

from typing import Any, Callable

from cae_agent.agent.attachments import classify_attachment
from cae_agent.core.config import AppConfig
from cae_agent.ui.files import (
    UIError,
    delete_input_file,
    format_bytes,
    input_file_summaries,
)


def build_input_file_library(
    ui: Any,
    config: AppConfig,
    *,
    selected_inputs: set[str],
    refresh_attachment_selection: Callable[[], None],
    overview_refresh: Callable[[], None],
    set_feedback: Callable[[str, str], None],
) -> Any:
    """채팅창에서 입력 파일을 바로 고르고 삭제할 수 있는 접이식 목록을 만든다."""

    def toggle_input_file(name: str, selected: bool) -> None:
        """체크박스 상태를 다음 메시지에 전달할 첨부 목록과 동기화한다."""
        if selected:
            selected_inputs.add(name)
        else:
            selected_inputs.discard(name)
        refresh_attachment_selection()
        input_file_library.refresh()

    def remove_input_file(name: str) -> None:
        """입력 폴더의 파일 하나를 삭제하고 선택 목록에서도 즉시 제거한다."""
        try:
            deleted = delete_input_file(config, name)
        except UIError as error:
            set_feedback(f"입력 파일 삭제 실패: {error}", "text-negative")
            return
        selected_inputs.discard(deleted)
        refresh_attachment_selection()
        overview_refresh()
        set_feedback(f"입력 파일 삭제 완료: {deleted}", "text-positive")
        input_file_library.refresh()

    @ui.refreshable
    def input_file_library() -> None:
        """현재 입력 폴더 파일을 채팅 작성기 안의 작은 선택 목록으로 표시한다."""
        files = input_file_summaries(config.workspace.input_dir)
        if not files:
            return
        with ui.expansion(
            f"입력 파일 {len(files)}개",
            icon="folder_open",
            value=False,
        ).classes("cae-input-library w-full"):
            for item in files:
                kind = classify_attachment(item.name)
                selected = item.name in selected_inputs
                with ui.row().classes(
                    "w-full items-center justify-between gap-2 "
                    "cae-input-library-row"
                ):
                    checkbox = ui.checkbox(
                        value=selected,
                        on_change=lambda event, name=item.name: (
                            toggle_input_file(name, bool(event.value))
                        ),
                    ).props("dense")
                    with ui.column().classes("min-w-0 flex-1 gap-0"):
                        ui.label(item.name).classes("text-sm font-medium truncate")
                        ui.label(
                            f"{kind.value} · {format_bytes(item.size_bytes)} · "
                            f"{item.modified_at:%m-%d %H:%M}"
                        ).classes("cae-muted text-xs")
                    ui.button(
                        icon="delete",
                        on_click=lambda name=item.name: remove_input_file(name),
                    ).props("flat dense round color=negative").tooltip(
                        "입력 파일 삭제"
                    )
                    checkbox.tooltip("다음 메시지에 첨부")

    input_file_library()
    return input_file_library
