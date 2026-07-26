"""CAE Agent 실행 전 로컬 환경의 준비 상태를 진단한다.

진단 기능은 외부 프로그램을 설치하거나 Ansys 라이선스를 점유하지 않는다.
사용자가 문제를 해결할 수 있도록 발견된 버전과 경로만 보고하며, 인증 토큰이나
환경변수의 실제 값처럼 민감할 수 있는 정보는 출력하지 않는다.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class CheckStatus(StrEnum):
    """개별 진단 항목이 가질 수 있는 상태."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """하나의 환경 진단 결과를 직렬화 가능한 형태로 보관한다."""

    name: str
    status: CheckStatus
    message: str
    details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """JSON 출력에 사용할 기본 자료형 사전을 반환한다."""
        data = asdict(self)
        data["status"] = self.status.value
        # JSON에서는 배열이 자연스러우므로 내부 불변 튜플을 목록으로 변환한다.
        data["details"] = list(self.details)
        return data


def check_operating_system(
    system_name: str | None = None,
) -> CheckResult:
    """현재 운영체제가 최초 지원 대상인 Windows인지 확인한다."""
    detected = system_name or platform.system()
    if detected == "Windows":
        return CheckResult(
            "operating_system",
            CheckStatus.PASS,
            f"지원되는 운영체제입니다: {detected}",
        )
    return CheckResult(
        "operating_system",
        CheckStatus.FAIL,
        f"현재 운영체제는 지원 대상이 아닙니다: {detected}",
        ("CAE Agent v0.1.0은 Windows만 공식 지원합니다.",),
    )


def check_python(
    version_info: tuple[int, int, int] | None = None,
) -> CheckResult:
    """실행 중인 Python이 패키지의 최소 버전을 만족하는지 확인한다."""
    version = version_info or (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    rendered = ".".join(str(part) for part in version)
    if version >= (3, 11, 0):
        return CheckResult(
            "python",
            CheckStatus.PASS,
            f"지원되는 Python 버전입니다: {rendered}",
        )
    return CheckResult(
        "python",
        CheckStatus.FAIL,
        f"Python 3.11 이상이 필요합니다: {rendered}",
    )


def check_virtual_environment(
    prefix: str | None = None,
    base_prefix: str | None = None,
) -> CheckResult:
    """현재 프로세스가 가상환경 안에서 실행되는지 확인한다."""
    active_prefix = prefix or sys.prefix
    original_prefix = base_prefix or sys.base_prefix
    if active_prefix != original_prefix:
        return CheckResult(
            "virtual_environment",
            CheckStatus.PASS,
            f"가상환경을 사용하고 있습니다: {active_prefix}",
        )
    return CheckResult(
        "virtual_environment",
        CheckStatus.WARN,
        "가상환경이 활성화되지 않았습니다.",
        ("프로젝트별 의존성 격리를 위해 .venv 사용을 권장합니다.",),
    )


def check_command(
    name: str,
    *,
    required: bool,
    finder=shutil.which,
) -> CheckResult:
    """PATH에서 외부 명령을 찾고 필수 여부에 따라 상태를 결정한다."""
    executable = finder(name)
    if executable:
        return CheckResult(
            name,
            CheckStatus.PASS,
            f"{name} 명령을 찾았습니다.",
            (str(executable),),
        )

    status = CheckStatus.FAIL if required else CheckStatus.WARN
    requirement = "필수" if required else "선택"
    return CheckResult(
        name,
        status,
        f"{requirement} 명령을 PATH에서 찾지 못했습니다: {name}",
    )


def discover_ansys_installations(
    environment: Mapping[str, str] | None = None,
    program_files: Path | None = None,
) -> tuple[Path, ...]:
    """환경변수와 표준 폴더에서 Ansys 설치 후보를 중복 없이 찾는다.

    Ansys는 버전별로 ``AWP_ROOT261``과 같은 환경변수를 제공할 수 있다.
    환경변수가 없는 설치도 있으므로 ``Program Files/ANSYS Inc`` 아래의
    ``v###`` 폴더도 함께 조사한다. 이 단계에서는 실행 파일을 시작하거나
    라이선스를 요청하지 않는다.
    """
    values = environment if environment is not None else os.environ
    candidates: list[Path] = []

    for key, value in values.items():
        if key.upper().startswith("AWP_ROOT") and value:
            path = Path(value).expanduser()
            if path.is_dir():
                candidates.append(path.resolve())

    if program_files is None:
        program_files_value = values.get("ProgramFiles")
        if program_files_value:
            program_files = Path(program_files_value)

    if program_files is not None:
        ansys_root = program_files / "ANSYS Inc"
        if ansys_root.is_dir():
            candidates.extend(
                path.resolve()
                for path in ansys_root.glob("v[0-9][0-9][0-9]")
                if path.is_dir()
            )

    # 환경변수와 표준 경로가 같은 설치를 가리킬 수 있으므로 문자열 비교가 아닌
    # Path 객체를 키로 사용해 중복을 제거하고 결과 순서를 안정적으로 유지한다.
    return tuple(sorted(set(candidates), key=lambda path: str(path).lower()))


def check_ansys(
    installations: Sequence[Path] | None = None,
) -> CheckResult:
    """발견된 Ansys 설치 후보를 보고한다."""
    found = (
        tuple(installations)
        if installations is not None
        else discover_ansys_installations()
    )
    if found:
        return CheckResult(
            "ansys",
            CheckStatus.PASS,
            f"Ansys 설치 후보 {len(found)}개를 찾았습니다.",
            tuple(str(path) for path in found),
        )
    return CheckResult(
        "ansys",
        CheckStatus.FAIL,
        "Ansys 설치 경로를 찾지 못했습니다.",
        (
            "AWP_ROOT### 환경변수 또는 Program Files의 ANSYS Inc 폴더를 "
            "확인하세요.",
        ),
    )


def check_workspace(workspace: Path) -> CheckResult:
    """작업공간을 준비하고 실제 임시 파일 쓰기가 가능한지 검증한다."""
    resolved = workspace.expanduser().resolve()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        # 권한 비트만 확인하면 Windows ACL이나 보안 프로그램의 차단을 놓칠 수
        # 있으므로 실제 파일을 만들고 닫은 뒤 자동 삭제하는 방식으로 검사한다.
        with tempfile.NamedTemporaryFile(dir=resolved, delete=True):
            pass
    except OSError as error:
        return CheckResult(
            "workspace",
            CheckStatus.FAIL,
            f"작업공간에 파일을 쓸 수 없습니다: {resolved}",
            (f"{type(error).__name__}: {error}",),
        )
    return CheckResult(
        "workspace",
        CheckStatus.PASS,
        f"작업공간을 사용할 수 있습니다: {resolved}",
    )


def run_checks(workspace: Path) -> list[CheckResult]:
    """정해진 순서로 전체 환경 진단을 실행한다."""
    return [
        check_operating_system(),
        check_python(),
        check_virtual_environment(),
        check_command("git", required=True),
        check_command("gh", required=False),
        check_command("codex", required=False),
        check_ansys(),
        check_workspace(workspace),
    ]


def render_text(results: Sequence[CheckResult]) -> str:
    """사람이 터미널에서 읽기 쉬운 여러 줄 결과를 만든다."""
    lines: list[str] = []
    for result in results:
        lines.append(f"[{result.status.value}] {result.message}")
        lines.extend(f"       - {detail}" for detail in result.details)
    return "\n".join(lines)


def render_json(results: Sequence[CheckResult]) -> str:
    """자동화 도구가 처리할 수 있는 JSON 결과를 만든다."""
    failed = any(result.status is CheckStatus.FAIL for result in results)
    payload = {
        "ok": not failed,
        "checks": [result.to_dict() for result in results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
