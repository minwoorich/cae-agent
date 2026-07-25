"""Codex CLI 어댑터의 안전한 호출 인자와 결과 보존을 검증한다."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from cae_agent.agents import AgentError, CodexProvider
from cae_agent.agents.codex import build_prompt
from cae_agent.config import load_config


def test_prompt_contains_target_version_and_safety_constraints() -> None:
    prompt = build_prompt(
        target="spaceclaim",
        request="직육면체를 생성한다.",
        ansys_version="261",
    )

    assert "SpaceClaim 내부 Python API" in prompt
    assert "V261" in prompt
    assert "절대경로" in prompt
    assert "Markdown 코드 펜스 없이" in prompt
    assert "ExtrudeType.ForceAdd" in prompt
    assert "result.CreatedBodies[0]" in prompt
    assert 'body.Name = "이름"' in prompt


def test_codex_runs_read_only_and_saves_validated_script(
    tmp_path: Path,
) -> None:
    config = load_config(current_directory=tmp_path)
    received: dict[str, object] = {}

    def runner(command, **kwargs):
        received["command"] = command
        received.update(kwargs)
        response_path = Path(
            command[command.index("--output-last-message") + 1]
        )
        response_path.write_text(
            json.dumps(
                {
                    "target": "spaceclaim",
                    "script": "# 상세한 한국어 주석\nvalue = 1\n",
                    "explanation": "테스트 형상을 생성합니다.",
                    "assumptions": ["SpaceClaim V261을 사용합니다."],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    provider = CodexProvider(
        runner=runner,
        executable_finder=lambda _name: "codex",
        run_id_factory=lambda: "fixed",
    )
    result = provider.generate(
        config,
        target="spaceclaim",
        request="테스트 형상을 생성한다.",
    )

    command = received["command"]
    assert command[0:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--output-schema" in command
    assert "--model" not in command
    assert received["input"].startswith("다음 요구사항")
    assert received["timeout"] == 300
    assert result.run_id == "fixed"
    assert Path(result.script_file).read_text(encoding="utf-8").startswith(
        "# -*- coding: utf-8 -*-\n# 상세한 한국어 주석"
    )
    metadata = json.loads(
        Path(result.metadata_file).read_text(encoding="utf-8")
    )
    assert metadata["provider"] == "codex"


def test_configured_model_is_passed_to_codex(tmp_path: Path) -> None:
    """모델을 명시한 경우에만 Codex 명령에 해당 모델 옵션이 포함되어야 한다."""
    config = load_config(current_directory=tmp_path)
    config = replace(config, agent=replace(config.agent, model="gpt-5.3-codex"))
    received: dict[str, list[str]] = {}

    def runner(command, **_kwargs):
        received["command"] = command
        response_path = Path(
            command[command.index("--output-last-message") + 1]
        )
        response_path.write_text(
            json.dumps(
                {
                    "target": "spaceclaim",
                    "script": "result = 1\n",
                    "explanation": "테스트 결과",
                    "assumptions": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    provider = CodexProvider(
        runner=runner,
        executable_finder=lambda _name: "codex",
        run_id_factory=lambda: "model-test",
    )
    provider.generate(config, target="spaceclaim", request="테스트")

    command = received["command"]
    assert command[command.index("--model") + 1] == "gpt-5.3-codex"


def test_missing_codex_is_reported(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    provider = CodexProvider(executable_finder=lambda _name: None)

    with pytest.raises(AgentError, match="찾지 못했습니다"):
        provider.generate(
            config,
            target="mechanical",
            request="온도 결과를 추가한다.",
        )


def test_nonzero_codex_exit_is_reported(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "authentication required",
        )

    provider = CodexProvider(
        runner=runner,
        executable_finder=lambda _name: "codex",
        run_id_factory=lambda: "fixed",
    )

    with pytest.raises(AgentError, match="종료 코드 1"):
        provider.generate(
            config,
            target="mechanical",
            request="온도 결과를 추가한다.",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "target": "mechanical",
            "script": "pass",
            "explanation": "대상이 다름",
            "assumptions": [],
        },
        {
            "target": "spaceclaim",
            "script": "```python\npass\n```",
            "explanation": "코드 펜스 포함",
            "assumptions": [],
        },
        {
            "target": "spaceclaim",
            "script": "if:",
            "explanation": "문법 오류",
            "assumptions": [],
        },
    ],
)
def test_invalid_structured_result_is_rejected(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    config = load_config(current_directory=tmp_path)

    def runner(command, **_kwargs):
        response_path = Path(
            command[command.index("--output-last-message") + 1]
        )
        response_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    provider = CodexProvider(
        runner=runner,
        executable_finder=lambda _name: "codex",
        run_id_factory=lambda: "fixed",
    )

    with pytest.raises(AgentError):
        provider.generate(
            config,
            target="spaceclaim",
            request="형상을 생성한다.",
        )
