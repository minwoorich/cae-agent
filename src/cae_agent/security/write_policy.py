"""배포용 UI에서 Codex가 변경할 수 있는 파일 경계를 판정한다.

CAE Agent의 설치 소스와 사용자 작업 산출물은 수명이 다르다. 이 모듈은
Codex App Server의 승인 요청을 사용자 작업공간 정책으로 다시 검사해,
핵심 프로그램 코드나 업로드 원본이 자연어 작업 도중 변경되지 않게 한다.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from cae_agent.security.approval import ApprovalRequest, ApprovalRisk
from cae_agent.core.config import WorkspaceConfig


class ApprovalDecision(StrEnum):
    """UI가 승인 요청 한 건에 적용할 최종 정책 결정."""

    AUTO_APPROVE = "auto_approve"
    MANUAL_APPROVAL = "manual_approval"
    DENY = "deny"


def _contains_symlink(root: Path, target: Path) -> bool:
    """루트부터 대상까지 이미 존재하는 구성 요소에 링크가 있는지 확인한다."""
    try:
        relative = target.relative_to(root)
    except ValueError:
        return True

    current = root
    if current.exists() and current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            return True
    return False


def is_generated_write_target(
    target_text: str,
    workspace: WorkspaceConfig,
) -> bool:
    """승인 대상이 실제 ``workspace/generated`` 내부인지 보수적으로 검사한다.

    App Server가 구체적인 ``grantRoot``를 제공하지 않고 "현재 작업공간"처럼
    넓은 대상을 요청하면 허용하지 않는다. 상대경로는 사용자 작업공간을
    기준으로 해석하며, ``..`` 경로 탈출과 심볼릭 링크도 거절한다.
    """
    if not target_text.strip() or target_text == "현재 작업공간":
        return False

    workspace_root = workspace.root.resolve()
    generated_root = workspace.generated_dir.resolve()
    requested = Path(target_text).expanduser()
    if not requested.is_absolute():
        requested = workspace_root / requested
    requested = requested.resolve(strict=False)

    if requested != generated_root and generated_root not in requested.parents:
        return False
    return not _contains_symlink(workspace_root, requested)


def approval_decision(
    request: ApprovalRequest,
    workspace: WorkspaceConfig,
) -> ApprovalDecision:
    """위험도와 대상 경로를 함께 검사해 자동·수동·거절을 결정한다.

    일반 읽기 명령은 기존처럼 자동 승인한다. 실제 CAE 실행과 삭제는 사용자
    확인을 유지한다. 파일 변경은 ``generated`` 내부의 작업별 스크립트에만
    자동 승인을 허용하고 나머지 위치는 사용자도 우회 승인할 수 없게 거절한다.
    """
    if request.risk in {ApprovalRisk.EXECUTE, ApprovalRisk.DELETE}:
        return ApprovalDecision.MANUAL_APPROVAL
    if request.risk is ApprovalRisk.ROUTINE:
        return ApprovalDecision.AUTO_APPROVE
    if request.method == "item/fileChange/requestApproval":
        return (
            ApprovalDecision.AUTO_APPROVE
            if is_generated_write_target(request.target, workspace)
            else ApprovalDecision.DENY
        )
    return ApprovalDecision.DENY
