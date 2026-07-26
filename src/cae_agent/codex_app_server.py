"""Codex App Server와 안전하게 통신하는 비동기 JSONL 어댑터.

이 모듈은 UI 프레임워크와 분리되어 있다. 따라서 NiceGUI가 설치되지 않은
환경에서도 프로토콜과 프로세스 수명 주기를 단위 테스트할 수 있다.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cae_agent.attachments import AttachmentKind, classify_attachment
from cae_agent.approval import (
    ApprovalRequest,
    append_approval_audit,
    build_approval_request,
)


class CodexAppServerError(RuntimeError):
    """사용자가 조치할 수 있는 한글 설명으로 변환된 App Server 오류."""


@dataclass(frozen=True, slots=True)
class CodexStreamEvent:
    """한 번의 Codex 응답에서 UI가 소비할 정규화된 이벤트."""

    kind: str
    text: str = ""
    status: str = ""
    approval: ApprovalRequest | None = None


class CodexAppServerClient:
    """로컬 Codex App Server 프로세스 한 개와 대화 스레드 한 개를 관리한다."""

    _APPROVAL_METHODS = {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "applyPatchApproval",
        "execCommandApproval",
    }

    def __init__(
        self,
        workspace: Path,
        *,
        executable: str = "codex",
        request_timeout: float = 30.0,
        audit_path: Path | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.executable = executable
        self.request_timeout = request_timeout
        self.audit_path = audit_path
        self.process: asyncio.subprocess.Process | None = None
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self._next_request_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._approvals: dict[int, ApprovalRequest] = {}
        self._approved_items: dict[str, ApprovalRequest] = {}

    @property
    def connected(self) -> bool:
        """App Server 프로세스가 실행 중이고 초기 스레드가 준비됐는지 반환한다."""
        return (
            self.process is not None
            and self.process.returncode is None
            and self.thread_id is not None
        )

    async def start(self) -> None:
        """App Server를 시작하고 사용자 승인 기반 작업공간 스레드를 준비한다."""
        if self.connected:
            return
        if shutil.which(self.executable) is None:
            raise CodexAppServerError(
                "Codex CLI를 찾지 못했습니다. Codex CLI를 설치한 뒤 "
                "`codex login`으로 로그인해 주세요."
            )
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.executable,
                "app-server",
                cwd=self.workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise CodexAppServerError(
                f"Codex App Server를 시작하지 못했습니다: {error}"
            ) from error

        self._reader_task = asyncio.create_task(self._read_messages())
        try:
            await self._request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "cae-agent-ui",
                        "title": "CAE Agent UI",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": False},
                },
            )
            await self._notify("initialized")
            response = await self._request(
                "thread/start",
                {
                    "cwd": str(self.workspace),
                    "approvalPolicy": "on-request",
                    # 기본 권한은 계속 읽기 전용으로 두고, 쓰기·실행은 아래 승인
                    # 요청 한 건에만 일회성으로 허용한다.
                    "sandbox": "read-only",
                    "developerInstructions": (
                        "사용자에게 한국어로 답하세요. 명령 실행이나 파일 변경은 "
                        "반드시 App Server 승인 요청을 통해 사용자 확인을 받으세요."
                    ),
                },
            )
            self.thread_id = str(response["thread"]["id"])
        except (KeyError, TypeError, CodexAppServerError) as error:
            await self.close()
            if isinstance(error, CodexAppServerError):
                raise
            raise CodexAppServerError(
                "Codex가 예상한 스레드 정보를 반환하지 않았습니다. "
                "Codex CLI를 최신 버전으로 업데이트해 주세요."
            ) from error

    async def stream_turn(
        self,
        prompt: str,
        *,
        attachments: tuple[Path, ...] = (),
    ) -> AsyncIterator[CodexStreamEvent]:
        """사용자 요청 한 건을 전송하고 텍스트 조각과 완료 상태를 순서대로 내보낸다."""
        await self.start()
        assert self.thread_id is not None

        inputs: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        non_image_attachments: list[Path] = []
        for path in attachments:
            if classify_attachment(path) is AttachmentKind.IMAGE:
                inputs.append({"type": "localImage", "path": str(path.resolve())})
            else:
                non_image_attachments.append(path)
        if non_image_attachments:
            attachment_lines = "\n".join(
                f"- [{classify_attachment(path).value}] {path.resolve()}"
                for path in non_image_attachments
            )
            inputs.append(
                {
                    "type": "text",
                    "text": (
                        "참고할 로컬 입력 파일 경로입니다. 파일을 변경하지 말고 "
                        f"읽기 전용으로만 검토하세요.\n{attachment_lines}"
                    ),
                }
            )
        response = await self._request(
            "turn/start",
            {"threadId": self.thread_id, "input": inputs},
        )
        try:
            self.turn_id = str(response["turn"]["id"])
        except (KeyError, TypeError) as error:
            raise CodexAppServerError(
                "Codex가 응답 작업 ID를 반환하지 않았습니다."
            ) from error

        while True:
            message = await self._events.get()
            method = message.get("method")
            params = message.get("params") or {}
            if params.get("turnId") not in (None, self.turn_id):
                continue
            if method == "item/agentMessage/delta":
                yield CodexStreamEvent(kind="delta", text=str(params["delta"]))
            elif method == "client/approvalRequested":
                approval = params.get("approval")
                if isinstance(approval, ApprovalRequest):
                    yield CodexStreamEvent(kind="approval", approval=approval)
            elif method == "error" and not params.get("willRetry", False):
                error = params.get("error") or {}
                raise CodexAppServerError(
                    str(error.get("message") or "Codex 응답 중 오류가 발생했습니다.")
                )
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                status = str(turn.get("status") or "failed")
                if status == "failed":
                    error = turn.get("error") or {}
                    raise CodexAppServerError(
                        str(error.get("message") or "Codex 응답이 실패했습니다.")
                    )
                yield CodexStreamEvent(kind="completed", status=status)
                return

    async def resolve_approval(
        self,
        request_id: int,
        fingerprint: str,
        *,
        approved: bool,
    ) -> None:
        """화면에 표시한 동일 요청에 한해서만 일회성 승인 결과를 보낸다."""
        request = self._approvals.pop(request_id, None)
        if request is None:
            raise CodexAppServerError("이미 처리됐거나 만료된 승인 요청입니다.")
        if request.fingerprint != fingerprint:
            await self._write(
                {"id": request_id, "result": {"decision": "decline"}}
            )
            self._audit(request, "invalidated", "승인 대상이 변경되었습니다.")
            raise CodexAppServerError(
                "승인 대상이 변경되어 이전 승인을 무효화했습니다."
            )
        decision = "accept" if approved else "decline"
        await self._write({"id": request_id, "result": {"decision": decision}})
        if approved:
            self._approved_items[request.item_id] = request
        self._audit(request, "approved" if approved else "declined")

    async def interrupt(self) -> None:
        """현재 응답이 진행 중이면 App Server에 중단 요청을 보낸다."""
        if self.thread_id is None or self.turn_id is None:
            return
        await self._request(
            "turn/interrupt",
            {"threadId": self.thread_id, "turnId": self.turn_id},
        )

    async def close(self) -> None:
        """대기 요청을 정리하고 자식 프로세스를 종료한다."""
        process, self.process = self.process, None
        self.thread_id = None
        self.turn_id = None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None
        self._fail_pending("Codex App Server 연결이 종료되었습니다.")

    async def _request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """JSON-RPC 요청을 보내고 같은 ID의 응답만 기다린다."""
        request_id = self._next_request_id
        self._next_request_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout=self.request_timeout)
        except TimeoutError as error:
            raise CodexAppServerError(
                f"Codex `{method}` 응답 시간이 초과되었습니다."
            ) from error
        finally:
            self._pending.pop(request_id, None)

    async def _notify(self, method: str) -> None:
        """응답을 기대하지 않는 JSON-RPC 알림을 보낸다."""
        await self._write({"method": method})

    async def _write(self, payload: dict[str, Any]) -> None:
        """민감정보를 로그에 남기지 않고 JSON 한 줄을 표준 입력으로 전송한다."""
        if self.process is None or self.process.stdin is None:
            raise CodexAppServerError("Codex App Server가 실행 중이 아닙니다.")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def _read_messages(self) -> None:
        """표준 출력 JSONL을 응답, 승인 요청, 일반 알림으로 분배한다."""
        assert self.process is not None and self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                request_id = message.get("id")
                if request_id in self._pending and "method" not in message:
                    future = self._pending[request_id]
                    if "error" in message:
                        future.set_exception(
                            CodexAppServerError(
                                self._rpc_error_message(message["error"])
                            )
                        )
                    else:
                        future.set_result(message.get("result") or {})
                elif request_id is not None and message.get("method") in {
                    "item/commandExecution/requestApproval",
                    "item/fileChange/requestApproval",
                }:
                    approval = build_approval_request(
                        int(request_id),
                        str(message["method"]),
                        message.get("params") or {},
                    )
                    self._approvals[int(request_id)] = approval
                    self._audit(approval, "requested")
                    await self._events.put(
                        {
                            "method": "client/approvalRequested",
                            "params": {
                                "turnId": (message.get("params") or {}).get(
                                    "turnId"
                                ),
                                "approval": approval,
                            },
                        }
                    )
                elif (
                    request_id is not None
                    and message.get("method") in self._APPROVAL_METHODS
                ):
                    # 광범위 권한과 레거시 승인은 세부 범위를 안전하게 표시할 수
                    # 없으므로 현재 버전에서는 계속 거절한다.
                    await self._write(
                        {"id": request_id, "result": {"decision": "decline"}}
                    )
                elif "method" in message:
                    if message.get("method") == "item/completed":
                        item = (message.get("params") or {}).get("item") or {}
                        approved = self._approved_items.pop(
                            str(item.get("id") or ""),
                            None,
                        )
                        if approved is not None:
                            self._audit(
                                approved,
                                "completed",
                                str(item.get("status") or "완료"),
                            )
                    await self._events.put(message)
        except asyncio.CancelledError:
            raise
        finally:
            self._fail_pending(
                "Codex App Server가 예기치 않게 종료되었습니다. "
                "`codex login status`를 확인한 뒤 다시 시도해 주세요."
            )

    def _fail_pending(self, message: str) -> None:
        """아직 끝나지 않은 요청에 동일한 연결 종료 오류를 전달한다."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(CodexAppServerError(message))

    def _audit(
        self,
        request: ApprovalRequest,
        event: str,
        detail: str = "",
    ) -> None:
        """감사 경로가 설정된 UI 실행에서만 승인 이벤트를 기록한다."""
        if self.audit_path is not None:
            append_approval_audit(
                self.audit_path,
                request,
                event,
                detail=detail,
            )

    @staticmethod
    def _rpc_error_message(error: Any) -> str:
        """서버 오류 객체에서 사용자에게 안전하게 표시할 메시지만 추출한다."""
        if isinstance(error, dict):
            return str(error.get("message") or "Codex 요청이 실패했습니다.")
        return "Codex 요청이 실패했습니다."
