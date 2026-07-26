"""Codex 채팅 세션, 진행 이벤트, 첨부와 채팅 패널 렌더링을 관리한다."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cae_agent.attachments import classify_attachment
from cae_agent.approval import ApprovalRequest, ApprovalRisk
from cae_agent.chat import (
    ChatError, ChatMessage, ChatSession, ChatStatus,
    MessageDetail, MessageDetailKind, MessageRole,
)
from cae_agent.codex_app_server import CodexAppServerClient, CodexAppServerError
from cae_agent.config import AppConfig
from cae_agent.ui_files import (
    MAX_UPLOAD_SIZE_BYTES, PendingUploadReplacement, UIError, UploadConflict,
    format_bytes as _format_bytes, replace_input_upload, store_input_upload,
)
from cae_agent.write_policy import ApprovalDecision, approval_decision


CHAT_SUBMIT_KEYDOWN_JS = """
(event) => {
    const isPlainEnter =
        event.key === 'Enter' && !event.shiftKey && !event.isComposing &&
        event.keyCode !== 229 && !event.repeat;
    if (isPlainEnter) { event.preventDefault(); emit(); }
}
"""


@dataclass(slots=True)
class ChatProgressStep:
    """한 assistant 응답에서 사용자에게 공개할 관찰 가능한 작업 단계."""

    step_id: str
    title: str
    status: str = "running"
    detail: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


def build_chat_panel(
    ui: Any,
    config: AppConfig,
    chat_tab: Any,
    overview_refresh: Callable[[], None],
    workbench_probe: Callable[[AppConfig], Any],
) -> None:
    """브라우저별 Codex 채팅 상태를 만들고 현재 탭 패널에 화면을 등록한다."""
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
        config.workspace.root,
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
        result = await asyncio.to_thread(workbench_probe, config)
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
                    decision = approval_decision(
                        event.approval,
                        config.workspace,
                    )
                    if decision is ApprovalDecision.MANUAL_APPROVAL:
                        pending_approvals[event.approval.request_id] = (
                            event.approval
                        )
                        approval_cards.refresh()
                        await scroll_chat_to_latest()
                        chat_status.set_text(
                            "위험 작업이 사용자 승인을 기다리고 있습니다."
                        )
                        chat_status.classes(replace="text-sm text-accent")
                    elif decision is ApprovalDecision.AUTO_APPROVE:
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
                    else:
                        await codex_client.resolve_approval(
                            event.approval.request_id,
                            event.approval.fingerprint,
                            approved=False,
                            automatic=True,
                        )
                        update_progress_step(
                            assistant.message_id,
                            step_id=f"approval-{event.approval.request_id}",
                            title="보호된 경로 변경을 차단했습니다",
                            status="failed",
                            detail=event.approval.target,
                        )
                        chat_status.set_text(
                            "핵심 소스와 보호된 작업공간 경로의 변경을 "
                            "안전 정책으로 차단했습니다."
                        )
                        chat_status.classes(replace="text-sm text-negative")
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
            overview_refresh()
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
            overview_refresh()
            refresh_attachment_selection()

    feedback: Any
    retention: Any
    candidate_box: Any
    approval_summary: Any


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
                        ).classes("cae-chat-input w-full").on(
                            "keydown",
                            send_chat_message,
                            js_handler=CHAT_SUBMIT_KEYDOWN_JS,
                        )
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

