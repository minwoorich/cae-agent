"""Icepak 대상 AI 프롬프트가 PyAEDT 실행 계약을 포함하는지 검증한다."""

from cae_agent.agent.providers.codex import build_prompt


def test_icepak_prompt_uses_injected_pyaedt_application() -> None:
    prompt = build_prompt(
        target="icepak",
        request="25 W 열원을 설정한다.",
        ansys_version="261",
    )

    assert "PyAEDT Ansys Icepak Python API" in prompt
    assert "icepak과 app 변수" in prompt
    assert "release_desktop" in prompt
