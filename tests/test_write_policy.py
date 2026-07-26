"""배포 UI의 파일 변경 허용 목록과 경로 탈출 차단을 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from cae_agent.security.approval import ApprovalRisk, ApprovalRequest
from cae_agent.core.config import WorkspaceConfig
from cae_agent.security.write_policy import (
    ApprovalDecision,
    approval_decision,
    is_generated_write_target,
)


def request(
    *,
    risk: ApprovalRisk,
    target: str,
    method: str = "item/fileChange/requestApproval",
) -> ApprovalRequest:
    """정책 판정에 필요한 최소 승인 요청을 일관된 값으로 만든다."""
    return ApprovalRequest(
        request_id=1,
        method=method,
        item_id="item-1",
        risk=risk,
        title="테스트 승인",
        target=target,
        reason="테스트",
        preview="테스트",
        fingerprint="fingerprint",
    )


def test_only_generated_directory_is_auto_approved(tmp_path: Path) -> None:
    """AI 스크립트 폴더 내부의 구체적인 파일 변경만 자동 승인해야 한다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")
    generated = workspace.generated_dir

    assert approval_decision(
        request(risk=ApprovalRisk.MODIFY, target=str(generated)),
        workspace,
    ) is ApprovalDecision.AUTO_APPROVE
    assert approval_decision(
        request(
            risk=ApprovalRisk.MODIFY,
            target=str(generated / "simplify_model.py"),
        ),
        workspace,
    ) is ApprovalDecision.AUTO_APPROVE


@pytest.mark.parametrize(
    "relative_target",
    [
        "input",
        "results",
        "logs",
        ".runtime",
        "../src/cae_agent/ui/dashboard.py",
        "",
    ],
)
def test_protected_and_ambiguous_targets_are_denied(
    tmp_path: Path,
    relative_target: str,
) -> None:
    """원본·결과·내부 상태·소스와 불명확한 대상은 사용자가 우회 승인할 수 없다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")
    target = (
        str(workspace.root / relative_target)
        if relative_target
        else "현재 작업공간"
    )

    assert approval_decision(
        request(risk=ApprovalRisk.MODIFY, target=target),
        workspace,
    ) is ApprovalDecision.DENY


def test_execution_still_requires_manual_approval(tmp_path: Path) -> None:
    """허용된 스크립트도 실제 CAE에서 실행할 때는 사용자 승인을 유지해야 한다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")

    assert approval_decision(
        request(
            risk=ApprovalRisk.EXECUTE,
            target=str(workspace.generated_dir / "model.py"),
            method="item/commandExecution/requestApproval",
        ),
        workspace,
    ) is ApprovalDecision.MANUAL_APPROVAL


@pytest.mark.parametrize("risk", [ApprovalRisk.EXECUTE, ApprovalRisk.DELETE])
def test_yolo_mode_auto_approves_dangerous_requests(
    tmp_path: Path,
    risk: ApprovalRisk,
) -> None:
    """YOLO 모드는 실행과 삭제 요청을 승인 카드 없이 자동 처리해야 한다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")

    assert approval_decision(
        request(
            risk=risk,
            target=str(workspace.root),
            method="item/commandExecution/requestApproval",
        ),
        workspace,
        yolo_mode=True,
    ) is ApprovalDecision.AUTO_APPROVE


def test_yolo_mode_cannot_override_protected_file_boundary(
    tmp_path: Path,
) -> None:
    """YOLO를 켜도 소스와 업로드 원본의 직접 파일 변경은 허용하지 않는다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")

    assert approval_decision(
        request(
            risk=ApprovalRisk.DELETE,
            target=str(workspace.input_dir / "original.step"),
        ),
        workspace,
        yolo_mode=True,
    ) is ApprovalDecision.DENY


def test_routine_read_only_command_is_auto_approved(tmp_path: Path) -> None:
    """상태 조회 같은 일반 명령은 기존의 끊김 없는 채팅 흐름을 유지해야 한다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")

    assert approval_decision(
        request(
            risk=ApprovalRisk.ROUTINE,
            target=str(workspace.root),
            method="item/commandExecution/requestApproval",
        ),
        workspace,
    ) is ApprovalDecision.AUTO_APPROVE


def test_generated_symlink_is_denied(tmp_path: Path) -> None:
    """generated가 작업공간 밖을 가리키는 링크이면 경로 문자열이 맞아도 거절한다."""
    workspace = WorkspaceConfig(tmp_path / "workspace")
    workspace.root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    try:
        workspace.generated_dir.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("현재 Windows 환경에서 심볼릭 링크를 만들 권한이 없습니다.")

    assert not is_generated_write_target(
        str(workspace.generated_dir / "model.py"),
        workspace,
    )
