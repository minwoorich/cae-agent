"""Codex 연결 전 채팅 세션의 전송·스트리밍·중지·재시도를 검증한다."""

import pytest

from cae_agent.chat import (
    ChatError,
    ChatSession,
    ChatStatus,
    MessageDetail,
    MessageDetailKind,
    MessageRole,
    mock_response_chunks,
)


def test_submit_and_complete_streaming_response() -> None:
    """사용자 요청, 첨부, 스트리밍 본문과 상세 카드가 순서대로 보존돼야 한다."""
    session = ChatSession()

    assistant = session.submit(
        "패키지 형상을 검토해줘",
        attachments=("package.step", "material.csv", "package.step"),
    )
    session.append_stream(assistant.message_id, "형상을 ")
    session.append_stream(assistant.message_id, "검토합니다.")
    detail = MessageDetail(
        kind=MessageDetailKind.SCRIPT,
        title="SpaceClaim 스크립트",
        content="# 아직 실행하지 않은 검토용 스크립트",
    )
    session.complete(assistant.message_id, details=(detail,))

    assert session.status is ChatStatus.IDLE
    assert session.active_assistant_id is None
    assert session.messages[0].role is MessageRole.USER
    assert session.messages[0].attachments == (
        "package.step",
        "material.csv",
    )
    assert session.messages[1].content == "형상을 검토합니다."
    assert session.messages[1].details == (detail,)


def test_submit_rejects_empty_and_duplicate_inflight_message() -> None:
    """빈 메시지와 응답 진행 중 중복 전송은 상태 모델에서 차단해야 한다."""
    session = ChatSession()

    with pytest.raises(ChatError, match="메시지를 입력"):
        session.submit("   ")

    session.submit("첫 요청")
    with pytest.raises(ChatError, match="생성하는 동안"):
        session.submit("중복 요청")


def test_stop_preserves_partial_response() -> None:
    """중지는 이미 도착한 응답을 지우지 않고 중단 상태로 전환해야 한다."""
    session = ChatSession()
    assistant = session.submit("긴 작업 계획을 보여줘")
    session.append_stream(assistant.message_id, "첫 번째 단계까지 수신")

    session.stop()

    assert session.status is ChatStatus.STOPPED
    assert session.active_assistant_id is None
    assert session.messages[-1].content == "첫 번째 단계까지 수신"
    with pytest.raises(ChatError, match="중지할 응답"):
        session.stop()


def test_fail_records_error_and_retry_reuses_last_request() -> None:
    """실패 원인은 별도 오류로 남기고 재시도는 마지막 요청과 첨부를 재사용한다."""
    session = ChatSession()
    assistant = session.submit(
        "열해석 계획을 작성해줘",
        attachments=("thermal.wbpj",),
    )
    session.fail(assistant.message_id, "모의 연결이 종료되었습니다.")

    retried = session.retry_last()

    assert session.messages[-3].role is MessageRole.ERROR
    assert "종료" in session.messages[-3].content
    assert session.messages[-2].attachments == ("thermal.wbpj",)
    assert session.messages[-1] is retried
    assert session.status is ChatStatus.STREAMING


def test_retry_requires_previous_user_message() -> None:
    """대화가 비어 있으면 다시 시도할 대상을 추측하지 않아야 한다."""
    with pytest.raises(ChatError, match="사용자 메시지가 없습니다"):
        ChatSession().retry_last()


def test_mock_response_is_explicitly_non_executing() -> None:
    """모의 응답은 첨부 대상을 보여주되 실제 실행으로 오해시키지 않아야 한다."""
    chunks = mock_response_chunks(
        "형상을 가져와줘",
        attachments=("model.step",),
    )
    response = "".join(chunks)

    assert "model.step" in response
    assert "Codex나 Ansys 명령을 실행하지 않았습니다" in response
    assert len(chunks) > 1
