"""Codex 실행 요청의 위험도, 일회성 승인과 감사 기록을 관리한다."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any


class ApprovalRisk(StrEnum):
    """사용자가 승인 카드에서 확인할 작업 위험 수준."""

    ROUTINE = "일반 작업"
    CREATE = "파일 생성"
    MODIFY = "파일·모델 변경"
    EXECUTE = "명령·해석 실행"
    DELETE = "삭제·초기화"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """App Server 승인 요청을 UI 표시용으로 정규화한 불변 스냅숏."""

    request_id: int
    method: str
    item_id: str
    risk: ApprovalRisk
    title: str
    target: str
    reason: str
    preview: str
    fingerprint: str


def _redact_secrets(text: str) -> str:
    """승인 카드와 감사 로그에 흔한 토큰 형식이 노출되지 않게 가린다."""
    patterns = (
        r"gh[pousr]_[A-Za-z0-9_]{20,}",
        r"sk-[A-Za-z0-9_-]{20,}",
        r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+",
        r"(?i)((?:api[_-]?key|token|password)\s*[:=]\s*)\S+",
    )
    redacted = text
    for pattern in patterns:
        redacted = re.sub(
            pattern,
            lambda match: (
                f"{match.group(1)}***" if match.lastindex else "***"
            ),
            redacted,
        )
    return redacted


def build_approval_request(
    request_id: int,
    method: str,
    params: dict[str, Any],
) -> ApprovalRequest:
    """명령 또는 파일 변경 요청을 보수적인 위험도로 분류한다."""
    item_id = str(params.get("itemId") or "unknown")
    if method == "item/commandExecution/requestApproval":
        command = _redact_secrets(
            str(params.get("command") or "(명령 내용 없음)")
        )
        lowered = command.lower()
        destructive_words = (
            "remove-item",
            " rm ",
            "del ",
            "delete",
            "--clear",
            "--overwrite",
            "workspace clean",
        )
        risk = (
            ApprovalRisk.DELETE
            if any(word in f" {lowered} " for word in destructive_words)
            else (
                ApprovalRisk.EXECUTE
                if any(
                    marker in lowered
                    for marker in (
                        "spaceclaim run",
                        "mechanical run-script",
                        "run-agent",
                        "workbench create",
                        "solve",
                    )
                )
                else ApprovalRisk.ROUTINE
            )
        )
        title = "명령 실행 승인"
        target = str(params.get("cwd") or "현재 작업공간")
        preview = command
    else:
        grant_root = str(params.get("grantRoot") or "현재 작업공간")
        reason_text = str(params.get("reason") or "")
        risk = (
            ApprovalRisk.DELETE
            if any(
                marker in reason_text.lower()
                for marker in ("delete", "remove", "clear", "overwrite", "삭제", "초기화")
            )
            else ApprovalRisk.MODIFY
        )
        title = "파일 변경 승인"
        target = grant_root
        preview = _redact_secrets(
            str(params.get("reason") or "Codex가 파일 변경 권한을 요청했습니다.")
        )

    reason = _redact_secrets(
        str(params.get("reason") or "Codex가 작업 수행에 승인을 요청했습니다.")
    )
    fingerprint_payload = {
        "method": method,
        "itemId": item_id,
        "target": target,
        "preview": preview,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ApprovalRequest(
        request_id=request_id,
        method=method,
        item_id=item_id,
        risk=risk,
        title=title,
        target=target,
        reason=reason,
        preview=preview,
        fingerprint=fingerprint,
    )


def requires_manual_approval(request: ApprovalRequest) -> bool:
    """복구가 어렵거나 CAE 자원을 실제 사용하는 요청만 수동 승인을 요구한다."""
    return request.risk in {ApprovalRisk.EXECUTE, ApprovalRisk.DELETE}


def append_approval_audit(
    audit_path: Path,
    request: ApprovalRequest,
    event: str,
    *,
    detail: str = "",
) -> None:
    """승인 수명 주기 한 단계를 비밀정보 없이 JSONL 감사 로그에 추가한다."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "detail": detail,
        **asdict(request),
    }
    with audit_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
