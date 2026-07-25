"""Codex CLI 비대화식 모드로 CAE Python 스크립트를 생성한다.

Codex에는 read-only sandbox만 제공하며, 최종 구조화 응답을 CAE Agent가 검증한
후 직접 작업공간에 저장한다. 생성과 실행을 분리하여 AI 응답이 검토 없이 Ansys
세션에서 실행되는 일을 방지한다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from cae_agent.agents.base import AgentError, GeneratedScript
from cae_agent.config import AppConfig, prepare_workspace


TARGETS = {"spaceclaim", "mechanical"}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "enum": sorted(TARGETS),
        },
        "script": {"type": "string", "minLength": 1},
        "explanation": {"type": "string", "minLength": 1},
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["target", "script", "explanation", "assumptions"],
    "additionalProperties": False,
}


def build_prompt(*, target: str, request: str, ansys_version: str) -> str:
    """대상 API와 출력 제약이 명확한 Codex 작업 지시를 만든다."""
    environment = (
        "Ansys SpaceClaim 내부 Python API"
        if target == "spaceclaim"
        else "Ansys Mechanical 내부 Python API"
    )
    return f"""다음 요구사항을 만족하는 CAE Python 스크립트를 작성하세요.

대상: {environment}
Ansys 내부 버전: V{ansys_version}
사용자 요구사항:
{request}

제약사항:
- 외부 CPython에서 실행되는 코드가 아니라 대상 Ansys 내부에서 실행될 코드입니다.
- 로컬 절대경로, 인증정보, 사용자별 경로를 포함하지 마세요.
- 파일 삭제, 프로세스 종료, 네트워크 요청을 포함하지 마세요.
- 스크립트 필드에는 Markdown 코드 펜스 없이 Python 소스만 넣으세요.
- 중요한 구현 의도와 Ansys API 제약은 자세한 한국어 주석으로 작성하세요.
- 확실하지 않은 모델 상태나 바디 이름은 assumptions에 명시하세요.
"""


def _validate_payload(payload: Any, *, target: str) -> dict[str, Any]:
    """JSON Schema 이후에도 실행 파일로 저장하기 위한 핵심 불변식을 검사한다."""
    if not isinstance(payload, dict):
        raise AgentError("Codex 최종 결과가 JSON 객체가 아닙니다.")
    required = {"target", "script", "explanation", "assumptions"}
    if set(payload) != required:
        raise AgentError("Codex 최종 결과의 필드 구성이 올바르지 않습니다.")
    if payload["target"] != target:
        raise AgentError("Codex 결과의 CAE 대상이 요청과 다릅니다.")
    script = payload["script"]
    if not isinstance(script, str) or not script.strip():
        raise AgentError("Codex가 비어 있는 스크립트를 반환했습니다.")
    if "```" in script:
        raise AgentError("Codex 스크립트에 Markdown 코드 펜스가 포함됐습니다.")
    if not isinstance(payload["explanation"], str):
        raise AgentError("Codex 설명이 문자열이 아닙니다.")
    assumptions = payload["assumptions"]
    if not isinstance(assumptions, list) or not all(
        isinstance(item, str) for item in assumptions
    ):
        raise AgentError("Codex 가정 목록이 올바르지 않습니다.")
    try:
        compile(script, "<codex-generated-script>", "exec")
    except SyntaxError as error:
        raise AgentError(
            f"Codex가 생성한 Python 문법이 올바르지 않습니다: {error}"
        ) from error
    return payload


class CodexProvider:
    """설치된 Codex CLI 인증을 재사용하는 read-only 스크립트 생성 제공자."""

    name = "codex"

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        executable_finder: Callable[[str], str | None] | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._executable_finder = executable_finder or shutil.which
        self._run_id_factory = run_id_factory or (lambda: uuid.uuid4().hex)

    def generate(
        self,
        config: AppConfig,
        *,
        target: str,
        request: str,
    ) -> GeneratedScript:
        """Codex를 호출하고 구조화 결과를 검증해 작업공간에 보존한다."""
        normalized_target = target.strip().lower()
        if normalized_target not in TARGETS:
            raise AgentError(
                "생성 대상은 spaceclaim 또는 mechanical이어야 합니다."
            )
        if not request.strip():
            raise AgentError("스크립트 생성 요구사항은 비어 있을 수 없습니다.")
        executable = self._executable_finder("codex")
        if executable is None:
            raise AgentError(
                "Codex CLI를 찾지 못했습니다. 설치와 로그인을 확인한 뒤 "
                "`cae-agent doctor`를 다시 실행하세요."
            )

        prepare_workspace(config.workspace)
        run_id = self._run_id_factory()
        runtime = config.workspace.root / ".runtime" / "codex" / run_id
        runtime.mkdir(parents=True, exist_ok=False)
        schema_file = runtime / "output.schema.json"
        response_file = runtime / "last-message.json"
        schema_file.write_text(
            json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        prompt = build_prompt(
            target=normalized_target,
            request=request.strip(),
            ansys_version=config.ansys.version,
        )
        command = [
            executable,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--output-schema",
            str(schema_file),
            "--output-last-message",
            str(response_file),
            "--color",
            "never",
            "-C",
            str(config.workspace.root),
            "-",
        ]
        # 모델을 생략하면 Codex 사용자의 현재 기본 설정을 그대로 존중한다. 구형 CLI와의
        # 호환이나 조직 정책 때문에 모델을 고정해야 할 때에만 명시적인 옵션을 추가한다.
        if config.agent.model is not None:
            command[2:2] = ["--model", config.agent.model]
        try:
            completed = self._runner(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=config.agent.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise AgentError(
                f"Codex 실행이 {config.agent.timeout_seconds}초를 초과했습니다."
            ) from error
        except OSError as error:
            raise AgentError(f"Codex CLI를 실행하지 못했습니다: {error}") from error

        if completed.returncode != 0:
            # stderr에는 진행 정보가 포함될 수 있으므로 마지막 부분만 오류에
            # 포함하고 인증 토큰이나 전체 환경변수는 절대 기록하지 않는다.
            detail = (completed.stderr or "").strip()[-2000:]
            if "requires a newer version of Codex" in detail:
                detail += (
                    "\n설치된 Codex CLI를 최신 버전으로 업데이트하거나 "
                    "[agent].model에 현재 CLI가 지원하는 모델을 지정하세요."
                )
            raise AgentError(
                f"Codex CLI가 종료 코드 {completed.returncode}를 반환했습니다: "
                f"{detail}"
            )
        if not response_file.is_file():
            raise AgentError("Codex가 최종 응답 파일을 생성하지 않았습니다.")
        try:
            payload = json.loads(response_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AgentError("Codex 최종 응답이 올바른 JSON이 아닙니다.") from error
        validated = _validate_payload(payload, target=normalized_target)

        script_file = (
            config.workspace.generated_dir
            / f"{normalized_target}_{run_id}.py"
        )
        metadata_file = (
            config.workspace.generated_dir
            / f"{normalized_target}_{run_id}.metadata.json"
        )
        script_file.write_text(validated["script"], encoding="utf-8")
        metadata = {
            "run_id": run_id,
            "provider": self.name,
            "target": normalized_target,
            "explanation": validated["explanation"],
            "assumptions": validated["assumptions"],
        }
        metadata_file.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return GeneratedScript(
            run_id=run_id,
            provider=self.name,
            target=normalized_target,
            script_file=str(script_file),
            metadata_file=str(metadata_file),
            explanation=validated["explanation"],
            assumptions=tuple(validated["assumptions"]),
        )
