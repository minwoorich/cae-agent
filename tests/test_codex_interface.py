"""Codex-first 인터페이스에 필요한 지침, Skill과 문서를 검증한다."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
SKILL_ROOT = ROOT / ".agents" / "skills" / "cae-agent"
SKILL = SKILL_ROOT / "SKILL.md"
OPENAI_YAML = SKILL_ROOT / "agents" / "openai.yaml"
GUIDE = ROOT / "docs" / "codex-first.ko.md"


def test_repository_exposes_cae_skill_to_codex() -> None:
    """저장소 지침이 자연어 CAE 요청을 로컬 Skill로 연결해야 한다."""
    agents = AGENTS.read_text(encoding="utf-8")
    skill = SKILL.read_text(encoding="utf-8")

    assert ".agents/skills/cae-agent/SKILL.md" in agents
    assert "사용자의 자연어 요청을 기본 인터페이스" in agents
    assert skill.startswith("---\nname: cae-agent\n")
    assert "Workbench" in skill
    assert "SpaceClaim" in skill
    assert "Mechanical" in skill


def test_skill_requires_approval_for_destructive_or_generated_execution() -> None:
    """Codex가 위험한 Ansys 변경을 승인 없이 실행하지 못하게 명시해야 한다."""
    combined = "\n".join(
        [
            AGENTS.read_text(encoding="utf-8"),
            SKILL.read_text(encoding="utf-8"),
            GUIDE.read_text(encoding="utf-8"),
        ]
    )

    for required in (
        "--clear",
        "--overwrite",
        "--approve-execution",
        "사용자 승인",
        "기존 모델",
    ):
        assert required in combined


def test_skill_distinguishes_top_level_codex_from_nested_adapter() -> None:
    """일반 자연어 작업에서 불필요한 Codex 중첩을 피하도록 안내해야 한다."""
    skill = SKILL.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")

    assert "최상위 조정자" in skill
    assert "`generate`나 `run-agent`를 호출하지 않는다" in skill
    assert "별도의 Codex CLI 프로세스" in guide


def test_skill_ui_metadata_is_valid_and_mentions_explicit_skill() -> None:
    """Skill UI 메타데이터가 필수 값과 명시적 Skill 이름을 포함해야 한다."""
    # openai.yaml은 현재 문자열 필드만 사용하는 작은 고정 파일이다. 이 검사를
    # 위해 PyYAML 같은 런타임 외부 의존성을 추가하면 기본 패키지가 가벼워야
    # 한다는 프로젝트 원칙과 어긋나므로, 필요한 계약을 UTF-8 원문에서 직접
    # 확인한다. 전체 YAML 구조 검증은 skill-creator의 quick_validate.py가
    # 별도로 담당한다.
    source = OPENAI_YAML.read_text(encoding="utf-8")

    assert source.startswith("interface:\n")
    assert 'display_name: "CAE Agent"' in source
    assert 'short_description: "Codex로 Ansys CAE 작업을 안전하게 실행"' in source
    assert "$cae-agent" in source


def test_readme_prioritizes_codex_first_guide() -> None:
    """README가 직접 명령보다 자연어 사용자 경로를 먼저 안내해야 한다."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    codex_section = readme.index("## Codex-first quick start")
    setup_section = readme.index("## Development setup")
    assert codex_section < setup_section
    assert "docs/codex-first.ko.md" in readme
