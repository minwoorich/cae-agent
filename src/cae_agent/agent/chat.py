"""Codex 연결과 독립적으로 검증할 수 있는 채팅 메시지·세션 상태를 관리한다.

이 모듈은 NiceGUI나 Codex 프로세스를 직접 import하지 않는다. 따라서 메시지
전송, 스트리밍 누적, 중지, 실패와 재시도 규칙을 UI 렌더링과 분리해 테스트할
수 있다. 실제 Codex App Server 연결은 후속 어댑터가 이 상태 모델을 사용한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class ChatError(RuntimeError):
    """현재 채팅 상태에서 허용되지 않은 사용자 동작을 요청했을 때의 오류."""


class MessageRole(StrEnum):
    """화면에서 구분해 표시할 메시지 작성자 역할."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"


class MessageDetailKind(StrEnum):
    """접이식 상세 카드에 표시할 구조화된 내용 종류."""

    SCRIPT = "script"
    COMMAND = "command"
    LOG = "log"


class ChatStatus(StrEnum):
    """한 로컬 대화에서 현재 진행 중인 응답 상태."""

    IDLE = "idle"
    STREAMING = "streaming"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MessageDetail:
    """채팅 본문과 분리해 접어둘 스크립트, 명령 또는 로그."""

    kind: MessageDetailKind
    title: str
    content: str


@dataclass(slots=True)
class ChatMessage:
    """스트리밍 중 본문을 누적할 수 있는 대화 메시지."""

    role: MessageRole
    content: str
    attachments: tuple[str, ...] = ()
    details: tuple[MessageDetail, ...] = ()
    created_at: datetime = field(
        default_factory=lambda: datetime.now().astimezone()
    )
    message_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(slots=True)
class ChatSession:
    """한 브라우저 UI에서 유지하는 로컬 대화와 활성 응답 상태."""

    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
    messages: list[ChatMessage] = field(default_factory=list)
    status: ChatStatus = ChatStatus.IDLE
    active_assistant_id: str | None = None

    def submit(
        self,
        text: str,
        *,
        attachments: tuple[str, ...] = (),
    ) -> ChatMessage:
        """사용자 메시지와 빈 응답 자리를 만들고 스트리밍을 시작한다."""
        if self.status is ChatStatus.STREAMING:
            raise ChatError("응답을 생성하는 동안 새 메시지를 보낼 수 없습니다.")
        normalized = text.strip()
        if not normalized:
            raise ChatError("메시지를 입력하세요.")

        unique_attachments = tuple(dict.fromkeys(attachments))
        self.messages.append(
            ChatMessage(
                role=MessageRole.USER,
                content=normalized,
                attachments=unique_attachments,
            )
        )
        assistant = ChatMessage(role=MessageRole.ASSISTANT, content="")
        self.messages.append(assistant)
        self.status = ChatStatus.STREAMING
        self.active_assistant_id = assistant.message_id
        return assistant

    def append_stream(self, message_id: str, chunk: str) -> None:
        """활성 Codex 메시지에 순서대로 수신한 텍스트 조각을 추가한다."""
        if self.status is not ChatStatus.STREAMING:
            raise ChatError("현재 스트리밍 중인 응답이 없습니다.")
        message = self._active_message(message_id)
        message.content += chunk

    def complete(
        self,
        message_id: str,
        *,
        details: tuple[MessageDetail, ...] = (),
    ) -> None:
        """활성 응답을 완료하고 구조화된 상세 카드를 함께 보관한다."""
        message = self._active_message(message_id)
        message.details = details
        self.status = ChatStatus.IDLE
        self.active_assistant_id = None

    def stop(self) -> None:
        """진행 중 응답을 중단하되 이미 받은 본문은 대화에 보존한다."""
        if self.status is not ChatStatus.STREAMING:
            raise ChatError("중지할 응답이 없습니다.")
        if self.active_assistant_id is not None:
            message = self._active_message(self.active_assistant_id)
            if not message.content:
                message.content = "응답이 시작되기 전에 중지했습니다."
        self.status = ChatStatus.STOPPED
        self.active_assistant_id = None

    def fail(self, message_id: str, reason: str) -> None:
        """활성 응답 실패를 기존 메시지와 별도의 오류 메시지로 기록한다."""
        message = self._active_message(message_id)
        if not message.content:
            message.content = "응답을 완료하지 못했습니다."
        self.messages.append(
            ChatMessage(
                role=MessageRole.ERROR,
                content=reason.strip() or "알 수 없는 채팅 오류가 발생했습니다.",
            )
        )
        self.status = ChatStatus.ERROR
        self.active_assistant_id = None

    def retry_last(self) -> ChatMessage:
        """가장 최근 사용자 요청과 첨부를 새 시도로 다시 제출한다."""
        if self.status is ChatStatus.STREAMING:
            raise ChatError("응답을 생성하는 동안 다시 시도할 수 없습니다.")
        for message in reversed(self.messages):
            if message.role is MessageRole.USER:
                return self.submit(
                    message.content,
                    attachments=message.attachments,
                )
        raise ChatError("다시 시도할 사용자 메시지가 없습니다.")

    def _active_message(self, message_id: str) -> ChatMessage:
        """활성 응답 식별자와 일치하는 assistant 메시지를 반환한다."""
        if self.active_assistant_id != message_id:
            raise ChatError("현재 활성 응답과 메시지 식별자가 일치하지 않습니다.")
        for message in reversed(self.messages):
            if (
                message.message_id == message_id
                and message.role is MessageRole.ASSISTANT
            ):
                return message
        raise ChatError("활성 assistant 메시지를 찾을 수 없습니다.")

    def to_dict(self) -> dict[str, Any]:
        """대화 목록을 재시작 후 복원할 수 있는 JSON 호환 값으로 변환한다."""
        return {
            "version": 1,
            "session_id": self.session_id,
            "messages": [
                {
                    "message_id": message.message_id,
                    "role": message.role.value,
                    "content": message.content,
                    "attachments": list(message.attachments),
                    "created_at": message.created_at.isoformat(),
                    "details": [
                        {
                            "kind": detail.kind.value,
                            "title": detail.title,
                            "content": detail.content,
                        }
                        for detail in message.details
                    ],
                }
                for message in self.messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatSession":
        """저장된 JSON 값을 안전한 대기 상태의 채팅 세션으로 복원한다."""
        session = cls(session_id=str(data.get("session_id") or uuid4().hex[:12]))
        raw_messages = data.get("messages", [])
        if not isinstance(raw_messages, list):
            raise ChatError("저장된 대화 형식이 올바르지 않습니다.")
        for raw in raw_messages:
            if not isinstance(raw, dict):
                continue
            try:
                role = MessageRole(str(raw["role"]))
                created_at = datetime.fromisoformat(str(raw["created_at"]))
            except (KeyError, TypeError, ValueError) as error:
                raise ChatError("저장된 메시지를 읽을 수 없습니다.") from error
            details: list[MessageDetail] = []
            for raw_detail in raw.get("details", []):
                if not isinstance(raw_detail, dict):
                    continue
                details.append(
                    MessageDetail(
                        kind=MessageDetailKind(str(raw_detail["kind"])),
                        title=str(raw_detail["title"]),
                        content=str(raw_detail["content"]),
                    )
                )
            session.messages.append(
                ChatMessage(
                    role=role,
                    content=str(raw.get("content") or ""),
                    attachments=tuple(
                        str(item) for item in raw.get("attachments", [])
                    ),
                    details=tuple(details),
                    created_at=created_at,
                    message_id=str(raw.get("message_id") or uuid4().hex),
                )
            )
        # 실행 중이던 턴은 재접속 후 이어 붙일 수 없으므로 대화 본문만 보존하고
        # 입력 가능한 상태로 되돌린다.
        session.status = ChatStatus.IDLE
        session.active_assistant_id = None
        return session


def save_chat_session(path: Path, session: ChatSession) -> None:
    """현재 채팅 세션을 작업공간 런타임 파일로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_chat_session(path: Path) -> ChatSession:
    """저장된 채팅 세션이 있으면 읽고 없으면 새 세션을 만든다."""
    if not path.is_file():
        return ChatSession()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ChatError(f"저장된 대화를 읽을 수 없습니다: {error}") from error
    if not isinstance(data, dict):
        raise ChatError("저장된 대화 형식이 올바르지 않습니다.")
    return ChatSession.from_dict(data)


def mock_response_chunks(
    prompt: str,
    *,
    attachments: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """실제 Codex 실행 없이 채팅 레이아웃을 검증할 한국어 응답 조각을 만든다."""
    target = (
        ", ".join(attachments)
        if attachments
        else "첨부되지 않은 현재 작업공간"
    )
    return (
        "요청을 확인했습니다. ",
        f"작업 대상은 {target}입니다. ",
        f"요청 내용은 “{prompt.strip()}”입니다.\n\n",
        "현재 화면은 UI 흐름을 검증하는 모의 응답 단계입니다. ",
        "아직 Codex나 Ansys 명령을 실행하지 않았습니다. ",
        "다음 단계에서 Codex App Server를 연결한 뒤에도 모델 변경과 해석은 "
        "예상 변경을 먼저 보여주고 별도 승인을 받겠습니다.",
    )
