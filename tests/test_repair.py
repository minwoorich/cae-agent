"""제한적 자동 수정 루프의 승인, 재시도와 이력 보존을 검증한다."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cae_agent.agents import GeneratedScript
from cae_agent.config import load_config
from cae_agent.repair import RepairError, run_repair_loop


class FakeProvider:
    """테스트마다 고유 스크립트를 만들고 받은 프롬프트를 기록한다."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def generate(self, config, *, target: str, request: str) -> GeneratedScript:
        self.requests.append(request)
        number = len(self.requests)
        config.workspace.generated_dir.mkdir(parents=True, exist_ok=True)
        script = config.workspace.generated_dir / f"{target}_fake_{number}.py"
        metadata = (
            config.workspace.generated_dir / f"{target}_fake_{number}.json"
        )
        script.write_text(
            f"# {number}번째 시도의 상세한 한국어 주석\nvalue = {number}\n",
            encoding="utf-8",
        )
        metadata.write_text("{}", encoding="utf-8")
        return GeneratedScript(
            run_id=f"generated-{number}",
            provider="fake",
            target=target,
            script_file=str(script),
            metadata_file=str(metadata),
            explanation="테스트",
            assumptions=(),
        )


def test_execution_requires_explicit_approval(tmp_path: Path) -> None:
    """승인이 없으면 AI 호출과 Ansys 실행보다 먼저 작업을 차단해야 한다."""
    provider = FakeProvider()
    with pytest.raises(RepairError, match="--approve-execution"):
        run_repair_loop(
            load_config(current_directory=tmp_path),
            target="spaceclaim",
            request="블록 생성",
            system_name="SYS",
            approve_execution=False,
            provider=provider,
        )
    assert provider.requests == []


def test_success_stops_without_unnecessary_retry(tmp_path: Path) -> None:
    """첫 실행이 성공하면 수정용 AI 호출을 추가로 수행하지 않아야 한다."""
    provider = FakeProvider()
    executed: list[str] = []

    def executor(_config, generated, **_kwargs):
        executed.append(generated.script_file)
        return "성공"

    result = run_repair_loop(
        load_config(current_directory=tmp_path),
        target="mechanical",
        request="온도 결과 추가",
        system_name="SYS",
        approve_execution=True,
        provider=provider,
        executor=executor,
        run_id_factory=lambda: "success",
    )
    assert result.success is True
    assert len(result.attempts) == 1
    assert len(provider.requests) == 1
    assert len(executed) == 1
    assert Path(result.history_file).is_file()


def test_failure_generates_repair_prompt_and_preserves_error(
    tmp_path: Path,
) -> None:
    """실패 원인과 이전 코드를 수정 프롬프트에 넣고 다음 시도에서 성공한다."""
    provider = FakeProvider()
    executions = 0

    def executor(_config, _generated, **_kwargs):
        nonlocal executions
        executions += 1
        if executions == 1:
            raise RuntimeError(
                rf"{tmp_path}\secret\model.py: NameError: 잘못된 API"
            )
        return "수정 후 성공"

    result = run_repair_loop(
        load_config(current_directory=tmp_path),
        target="spaceclaim",
        request="블록 생성",
        system_name="SYS",
        approve_execution=True,
        provider=provider,
        executor=executor,
        run_id_factory=lambda: "repair",
    )
    assert result.success is True
    assert [attempt.status for attempt in result.attempts] == [
        "failed",
        "success",
    ]
    assert "이전 실행 스크립트" in provider.requests[1]
    assert "NameError" in provider.requests[1]
    assert str(tmp_path) not in provider.requests[1]
    assert Path(result.attempts[0].error_file).read_text(
        encoding="utf-8"
    ).rstrip().endswith("NameError: 잘못된 API")


def test_retry_count_never_exceeds_configuration(tmp_path: Path) -> None:
    """최초 실행과 설정된 수정 횟수를 합친 수 이상으로 실행하지 않는다."""
    config = load_config(current_directory=tmp_path)
    config = replace(config, agent=replace(config.agent, max_retries=2))
    provider = FakeProvider()

    def failing_executor(_config, _generated, **_kwargs):
        raise RuntimeError("항상 실패")

    result = run_repair_loop(
        config,
        target="mechanical",
        request="해석 실행",
        system_name="SYS",
        approve_execution=True,
        provider=provider,
        executor=failing_executor,
        run_id_factory=lambda: "failed",
    )
    assert result.success is False
    assert len(result.attempts) == 3
    assert len(provider.requests) == 3
    history = json.loads(Path(result.history_file).read_text(encoding="utf-8"))
    assert history["success"] is False
    assert len(history["attempts"]) == 3
