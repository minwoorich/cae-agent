"""AI 생성 스크립트의 실행 실패를 제한적으로 수정하고 재시도한다.

이 모듈은 AI 제공자와 Ansys 실행기를 직접 결합하되, 실행 승인과 최대 반복 횟수를
명시적으로 검사한다. 각 시도는 별도 생성 파일과 오류 파일로 남기므로 자동 수정이
원래 코드와 실패 원인을 덮어쓰지 않는다.
"""

from __future__ import annotations

import json
import re
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from cae_agent.agent.providers import CodexProvider, GeneratedScript
from cae_agent.core.config import AppConfig, prepare_workspace
from cae_agent.ansys.mechanical import run_mechanical_script
from cae_agent.ansys.spaceclaim import run_spaceclaim_script


class RepairError(RuntimeError):
    """자동 수정 루프를 안전하게 시작하거나 계속할 수 없을 때의 오류."""


class ScriptProvider(Protocol):
    """자동 수정기가 요구하는 최소 AI 제공자 인터페이스."""

    def generate(
        self,
        config: AppConfig,
        *,
        target: str,
        request: str,
    ) -> GeneratedScript:
        """요구사항에 맞는 스크립트를 생성하고 보존한다."""


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    """한 번의 생성 및 실행 시도에서 감사용으로 보존할 정보."""

    number: int
    generated: GeneratedScript
    status: str
    execution_result: str | None
    error_file: str | None


@dataclass(frozen=True, slots=True)
class RepairResult:
    """제한된 자동 수정 루프의 최종 결과와 전체 시도 이력."""

    run_id: str
    target: str
    success: bool
    attempts: tuple[RepairAttempt, ...]
    history_file: str
    last_error: str | None

    def to_json(self) -> str:
        """CLI와 외부 자동화가 사용할 구조화 결과를 반환한다."""
        payload = asdict(self)
        payload["attempts"] = [asdict(attempt) for attempt in self.attempts]
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _sanitize_error(error: str, config: AppConfig) -> str:
    """Codex에 전달하기 전에 로컬 절대경로와 지나치게 긴 로그를 제거한다."""
    sanitized = error.replace(str(config.workspace.root), "<WORKSPACE>")
    sanitized = sanitized.replace(str(Path.home()), "<USER_HOME>")
    # Windows traceback의 나머지 절대경로도 줄 단위로 가린다. 오류 종류와 다음
    # traceback 줄은 유지하면서 사용자명이나 설치 위치가 모델에 전달되지 않는다.
    sanitized = re.sub(
        r"(?im)\b[A-Z]:\\[^\r\n]*",
        "<LOCAL_PATH>",
        sanitized,
    )
    return sanitized[-8000:]


def build_repair_request(
    *,
    original_request: str,
    previous_script: str,
    error: str,
    attempt_number: int,
) -> str:
    """이전 코드와 실패 원인을 포함한 수정 전용 요구사항을 작성한다."""
    return f"""원래 사용자 요구사항:
{original_request}

이전 실행 스크립트:
--- 이전 스크립트 시작 ---
{previous_script}
--- 이전 스크립트 끝 ---

Ansys 실행 오류:
--- 오류 시작 ---
{error}
--- 오류 끝 ---

위 오류의 원인을 수정한 전체 스크립트를 다시 작성하세요.
현재 수정 시도 번호는 {attempt_number}입니다.
- 이전 스크립트의 올바른 부분은 유지하세요.
- 오류 메시지에 근거하지 않은 대규모 변경은 피하세요.
- 로컬 경로를 새로 만들거나 추측하지 마세요.
- 중요한 수정 이유를 자세한 한국어 주석과 explanation에 기록하세요.
"""


def _default_executor(
    config: AppConfig,
    generated: GeneratedScript,
    *,
    system_name: str,
    clear_geometry: bool,
) -> Any:
    """생성 대상에 맞는 기존 Ansys 실행 계층으로 스크립트를 전달한다."""
    script_file = Path(generated.script_file)
    if generated.target == "spaceclaim":
        return run_spaceclaim_script(
            config,
            script_file,
            system_name=system_name,
            clear_geometry=clear_geometry,
        )
    return run_mechanical_script(
        config,
        script_file,
        system_name=system_name,
    )


def run_repair_loop(
    config: AppConfig,
    *,
    target: str,
    request: str,
    system_name: str,
    approve_execution: bool,
    clear_geometry: bool = False,
    provider: ScriptProvider | None = None,
    executor: Callable[..., Any] | None = None,
    run_id_factory: Callable[[], str] | None = None,
) -> RepairResult:
    """생성 코드를 승인된 Ansys 세션에서 실행하고 실패할 때만 수정한다."""
    if not approve_execution:
        raise RepairError(
            "AI 생성 스크립트 실행에는 --approve-execution 승인이 필요합니다."
        )
    if target not in {"spaceclaim", "mechanical"}:
        raise RepairError("실행 대상은 spaceclaim 또는 mechanical이어야 합니다.")
    if clear_geometry and target != "spaceclaim":
        raise RepairError("--clear 옵션은 SpaceClaim 대상에서만 사용할 수 있습니다.")
    if not request.strip():
        raise RepairError("자동 수정 작업의 요구사항은 비어 있을 수 없습니다.")
    if not system_name.strip():
        raise RepairError("Workbench 시스템 이름은 비어 있을 수 없습니다.")

    prepare_workspace(config.workspace)
    active_provider = provider or CodexProvider()
    active_executor = executor or _default_executor
    run_id = (run_id_factory or (lambda: uuid.uuid4().hex))()
    history_file = (
        config.workspace.logs_dir / f"agent_{run_id}.history.json"
    )
    attempts: list[RepairAttempt] = []
    current_request = request.strip()
    last_error: str | None = None

    # max_retries는 최초 실행 이후 허용할 수정 횟수다. 따라서 총 실행 횟수는
    # 언제나 1 + max_retries 이하이며 성공하면 즉시 반복을 끝낸다.
    for number in range(1, config.agent.max_retries + 2):
        generated = active_provider.generate(
            config,
            target=target,
            request=current_request,
        )
        try:
            execution = active_executor(
                config,
                generated,
                system_name=system_name,
                clear_geometry=clear_geometry,
            )
        except Exception as error:
            # 예외 체인과 traceback을 그대로 로컬에 남겨 Ansys 래퍼, 연결 계층,
            # 사용자 스크립트 중 어디서 실패했는지 나중에도 재현할 수 있게 한다.
            raw_error = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
            error_file = (
                config.workspace.logs_dir
                / f"agent_{run_id}_attempt_{number}.error.txt"
            )
            error_file.write_text(raw_error, encoding="utf-8")
            last_error = _sanitize_error(raw_error, config)
            attempts.append(
                RepairAttempt(
                    number=number,
                    generated=generated,
                    status="failed",
                    execution_result=None,
                    error_file=str(error_file),
                )
            )
            _write_history(
                history_file,
                run_id=run_id,
                target=target,
                attempts=attempts,
                success=False,
                last_error=last_error,
            )
            if number > config.agent.max_retries:
                break
            previous_script = Path(generated.script_file).read_text(
                encoding="utf-8"
            )
            current_request = build_repair_request(
                original_request=request.strip(),
                previous_script=previous_script,
                error=last_error,
                attempt_number=number,
            )
            continue

        attempts.append(
            RepairAttempt(
                number=number,
                generated=generated,
                status="success",
                execution_result=(
                    execution.to_json()
                    if hasattr(execution, "to_json")
                    else str(execution)
                ),
                error_file=None,
            )
        )
        _write_history(
            history_file,
            run_id=run_id,
            target=target,
            attempts=attempts,
            success=True,
            last_error=None,
        )
        return RepairResult(
            run_id=run_id,
            target=target,
            success=True,
            attempts=tuple(attempts),
            history_file=str(history_file),
            last_error=None,
        )

    return RepairResult(
        run_id=run_id,
        target=target,
        success=False,
        attempts=tuple(attempts),
        history_file=str(history_file),
        last_error=last_error,
    )


def _write_history(
    history_file: Path,
    *,
    run_id: str,
    target: str,
    attempts: list[RepairAttempt],
    success: bool,
    last_error: str | None,
) -> None:
    """현재까지의 시도 이력을 UTF-8 JSON으로 매번 갱신한다."""
    payload = {
        "run_id": run_id,
        "target": target,
        "success": success,
        "attempts": [asdict(attempt) for attempt in attempts],
        "last_error": last_error,
    }
    history_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
