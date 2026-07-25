"""공식 전력반도체 예제의 정적 재현성 조건을 검증한다."""

import json
import tomllib
from pathlib import Path


EXAMPLE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "power-semiconductor-thermal"
)


def test_example_configuration_is_valid_toml() -> None:
    with (EXAMPLE_ROOT / "cae-agent.toml").open("rb") as stream:
        config = tomllib.load(stream)

    assert config["ansys"]["version"] == "261"
    assert config["workspace"]["root"] == "workspace"


def test_example_scripts_have_valid_python_syntax() -> None:
    scripts = [
        EXAMPLE_ROOT / "geometry" / "power_semiconductor.py",
        EXAMPLE_ROOT / "workbench" / "define_materials.wbjn",
        EXAMPLE_ROOT / "mechanical" / "setup_analysis.py",
        EXAMPLE_ROOT / "mechanical" / "solve_and_summarize.py",
    ]

    for script in scripts:
        compile(
            script.read_text(encoding="utf-8"),
            str(script),
            "exec",
        )


def test_result_schema_is_valid_json_with_required_fields() -> None:
    schema = json.loads(
        (
            EXAMPLE_ROOT / "expected" / "result.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert schema["type"] == "object"
    assert "temperature_max" in schema["required"]
    assert "baseline_rth_k_per_w" in schema["required"]


def test_example_has_no_local_absolute_windows_paths() -> None:
    """예제 파일이 개발자 PC의 드라이브 경로에 의존하지 않는지 확인한다."""
    for path in EXAMPLE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        assert "C:\\" not in content
        assert "C:/" not in content
