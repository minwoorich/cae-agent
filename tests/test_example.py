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


def test_v261_baseline_has_physical_acceptance_values() -> None:
    baseline = json.loads(
        (
            EXAMPLE_ROOT / "expected" / "v261-baseline.json"
        ).read_text(encoding="utf-8")
    )

    assert baseline["solver_status"] == "Done"
    assert baseline["node_count"] > 0
    assert baseline["element_count"] > 0
    assert baseline["temperature_max_c"] > baseline["base_temperature_c"]
    assert baseline["baseline_rth_k_per_w"] > 0
    assert (
        baseline["acceptance"]["temperature_max_relative_tolerance"]
        == 0.02
    )


def test_example_has_no_local_absolute_windows_paths() -> None:
    """예제 파일이 개발자 PC의 드라이브 경로에 의존하지 않는지 확인한다."""
    for path in EXAMPLE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        # 실제 통합 실행에서 생성되는 workspace에는 Ansys 로그와 절대경로가
        # 포함될 수 있다. 이 폴더는 Git에서 제외되므로 배포 소스 검사 대상에서
        # 제외하고, 저장소에 포함되는 예제 입력만 검증한다.
        if path.relative_to(EXAMPLE_ROOT).parts[0] == "workspace":
            continue
        content = path.read_text(encoding="utf-8")
        assert "C:\\" not in content
        assert "C:/" not in content
