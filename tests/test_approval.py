"""승인 위험도, 대상 무결성과 감사 로그를 검증한다."""

import json
from pathlib import Path

from cae_agent.approval import (
    ApprovalRisk,
    append_approval_audit,
    build_approval_request,
)


def test_destructive_command_is_highest_risk() -> None:
    """삭제나 초기화 명령은 일반 실행보다 높은 위험도로 분류한다."""
    request = build_approval_request(
        1,
        "item/commandExecution/requestApproval",
        {
            "itemId": "item-1",
            "command": "cae-agent spaceclaim run model.py --clear",
            "cwd": "C:/workspace",
        },
    )

    assert request.risk is ApprovalRisk.DELETE
    assert "--clear" in request.preview


def test_changed_target_has_different_fingerprint() -> None:
    """명령이나 대상이 달라지면 이전 승인 지문을 재사용할 수 없어야 한다."""
    first = build_approval_request(
        1,
        "item/commandExecution/requestApproval",
        {"itemId": "same", "command": "first", "cwd": "C:/workspace"},
    )
    changed = build_approval_request(
        2,
        "item/commandExecution/requestApproval",
        {"itemId": "same", "command": "second", "cwd": "C:/workspace"},
    )

    assert first.fingerprint != changed.fingerprint


def test_audit_log_is_append_only_jsonl(tmp_path: Path) -> None:
    """요청과 결정은 같은 감사 파일에 시간 순서대로 추가돼야 한다."""
    request = build_approval_request(
        3,
        "item/fileChange/requestApproval",
        {"itemId": "file-1", "reason": "새 스크립트 작성"},
    )
    audit_path = tmp_path / "logs" / "approvals.jsonl"

    append_approval_audit(audit_path, request, "requested")
    append_approval_audit(audit_path, request, "approved")

    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in records] == [
        "requested",
        "approved",
    ]
    assert all(record["fingerprint"] == request.fingerprint for record in records)


def test_command_preview_redacts_token() -> None:
    """승인 카드와 감사 로그에 접근 토큰 원문을 남기지 않아야 한다."""
    request = build_approval_request(
        4,
        "item/commandExecution/requestApproval",
        {
            "itemId": "secret",
            "command": "tool --token=ghp_abcdefghijklmnopqrstuvwxyz123456",
        },
    )

    assert "ghp_" not in request.preview
    assert "***" in request.preview
