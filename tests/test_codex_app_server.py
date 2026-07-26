"""Codex App Server 어댑터의 프로토콜과 오류 처리를 검증한다."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cae_agent.codex_app_server import (
    CodexAppServerClient,
    CodexAppServerError,
)


class FakeWriter:
    """실제 프로세스 없이 전송된 JSONL을 보관하는 비동기 writer."""

    def __init__(self) -> None:
        self.lines: list[dict[str, object]] = []

    def write(self, data: bytes) -> None:
        self.lines.append(json.loads(data))

    async def drain(self) -> None:
        return None


class FakeProcess:
    """테스트가 필요한 표준 입출력과 종료 상태만 제공한다."""

    def __init__(self) -> None:
        self.stdin = FakeWriter()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode or 0


def feed(process: FakeProcess, payload: dict[str, object]) -> None:
    """가짜 표준 출력에 서버 JSON 한 줄을 주입한다."""
    process.stdout.feed_data(
        json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    )


async def wait_for_writes(process: FakeProcess, count: int) -> None:
    """이벤트 루프 속도와 무관하게 지정한 요청 수가 기록될 때까지 기다린다."""
    for _ in range(100):
        if len(process.stdin.lines) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"예상한 JSONL 요청 {count}개가 기록되지 않았습니다.")


def test_start_and_stream_turn_use_read_only_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """초기화부터 텍스트 델타와 완료까지 순서가 유지되는지 확인한다."""
    asyncio.run(
        _start_and_stream_turn_use_read_only_protocol(monkeypatch, tmp_path)
    )


async def _start_and_stream_turn_use_read_only_protocol(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """동기 pytest 환경에서 실행할 비동기 프로토콜 검증 본문."""
    process = FakeProcess()

    async def create_process(*args: object, **kwargs: object) -> FakeProcess:
        return process

    monkeypatch.setattr("shutil.which", lambda name: "codex.exe")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    client = CodexAppServerClient(tmp_path)

    start_task = asyncio.create_task(client.start())
    await wait_for_writes(process, 1)
    feed(process, {"id": 1, "result": {}})
    # initialized 알림과 thread/start 요청이 모두 기록된 뒤 응답해야 한다.
    await wait_for_writes(process, 3)
    feed(
        process,
        {"id": 2, "result": {"thread": {"id": "thread-1"}}},
    )
    await start_task

    async def collect() -> list[tuple[str, str]]:
        return [
            (event.kind, event.text or event.status)
            async for event in client.stream_turn("열해석 계획을 알려줘")
        ]

    stream_task = asyncio.create_task(collect())
    await wait_for_writes(process, 4)
    feed(process, {"id": 3, "result": {"turn": {"id": "turn-1"}}})
    await asyncio.sleep(0)
    feed(
        process,
        {
            "method": "item/agentMessage/delta",
            "params": {"turnId": "turn-1", "delta": "계획입니다."},
        },
    )
    feed(
        process,
        {
            "method": "turn/completed",
            "params": {
                "turnId": "turn-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        },
    )
    assert await stream_task == [
        ("delta", "계획입니다."),
        ("completed", "completed"),
    ]
    assert process.stdin.lines[1] == {"method": "initialized"}
    thread_params = process.stdin.lines[2]["params"]
    assert thread_params["sandbox"] == "read-only"
    assert thread_params["approvalPolicy"] == "on-request"
    await client.close()


def test_approval_request_is_declined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """승인 UI가 없는 단계에서는 명령 실행 요청을 자동 거절한다."""
    asyncio.run(_approval_request_is_declined(monkeypatch, tmp_path))


async def _approval_request_is_declined(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """동기 pytest 환경에서 실행할 비동기 승인 거절 검증 본문."""
    process = FakeProcess()
    client = CodexAppServerClient(tmp_path)
    client.process = process  # type: ignore[assignment]
    client._reader_task = asyncio.create_task(client._read_messages())
    feed(
        process,
        {
            "id": 77,
            "method": "item/commandExecution/requestApproval",
            "params": {},
        },
    )
    await asyncio.sleep(0)
    assert process.stdin.lines == [
        {"id": 77, "result": {"decision": "decline"}}
    ]
    await client.close()


def test_missing_codex_has_korean_recovery_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex 미설치 환경은 추적 정보 대신 설치·로그인 안내를 보여준다."""
    asyncio.run(_missing_codex_has_korean_recovery_message(monkeypatch, tmp_path))


async def _missing_codex_has_korean_recovery_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """동기 pytest 환경에서 실행할 비동기 미설치 오류 검증 본문."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    client = CodexAppServerClient(tmp_path)
    with pytest.raises(CodexAppServerError, match="Codex CLI를 찾지 못했습니다"):
        await client.start()
