"""CAE Agent의 설정 로드, 검증 및 작업공간 생성을 담당한다.

설정 파일은 Python 코드를 실행할 수 없는 TOML 형식만 지원한다. API 키나
GitHub 토큰 같은 비밀정보는 이 모델에 포함하지 않으며, 향후 필요한 인증정보는
각 CLI의 안전한 인증 저장소나 환경변수를 통해 별도로 전달한다.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_NAME = "cae-agent.toml"


class ConfigError(ValueError):
    """설정 파일을 읽거나 검증할 수 없을 때 발생하는 사용자 오류."""


@dataclass(frozen=True, slots=True)
class AnsysConfig:
    """Workbench 실행과 연결에 필요한 Ansys 설정."""

    version: str = "261"
    workbench_port: int = 50055
    headless: bool = False


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """AI 에이전트 제공자와 제한된 재시도 정책 설정."""

    provider: str = "codex"
    max_retries: int = 3


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """한 CAE 작업에서 생성되는 파일을 격리할 루트 경로."""

    root: Path

    @property
    def input_dir(self) -> Path:
        """사용자가 제공한 원본 입력 파일을 보관할 경로."""
        return self.root / "input"

    @property
    def generated_dir(self) -> Path:
        """AI가 생성하거나 수정한 스크립트를 보관할 경로."""
        return self.root / "generated"

    @property
    def logs_dir(self) -> Path:
        """Workbench와 Mechanical 실행 로그를 보관할 경로."""
        return self.root / "logs"

    @property
    def results_dir(self) -> Path:
        """해석 결과와 후처리 산출물을 보관할 경로."""
        return self.root / "results"

    def directories(self) -> tuple[Path, ...]:
        """생성해야 하는 작업공간 경로를 부모부터 순서대로 반환한다."""
        return (
            self.root,
            self.input_dir,
            self.generated_dir,
            self.logs_dir,
            self.results_dir,
        )


@dataclass(frozen=True, slots=True)
class AppConfig:
    """CAE Agent 프로세스 전체에서 사용하는 검증 완료 설정."""

    ansys: AnsysConfig
    agent: AgentConfig
    workspace: WorkspaceConfig
    source_file: Path | None = None

    def to_dict(self) -> dict[str, object]:
        """경로를 문자열로 변환한 공개 설정 사전을 반환한다."""
        return {
            "ansys": asdict(self.ansys),
            "agent": asdict(self.agent),
            "workspace": {
                "root": str(self.workspace.root),
                "input": str(self.workspace.input_dir),
                "generated": str(self.workspace.generated_dir),
                "logs": str(self.workspace.logs_dir),
                "results": str(self.workspace.results_dir),
            },
            "source_file": (
                str(self.source_file) if self.source_file is not None else None
            ),
        }


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    """선택 TOML 테이블이 사전 형태인지 검증해 반환한다."""
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] 설정은 TOML 테이블이어야 합니다.")
    return value


def _string(table: dict[str, Any], key: str, default: str) -> str:
    """빈 문자열을 허용하지 않는 문자열 설정값을 읽는다."""
    value = table.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} 설정은 비어 있지 않은 문자열이어야 합니다.")
    return value.strip()


def _integer(
    table: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """bool을 정수로 오인하지 않고 지정된 범위의 정수만 허용한다."""
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} 설정은 정수여야 합니다.")
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"{key} 설정은 {minimum} 이상 {maximum} 이하여야 합니다."
        )
    return value


def _boolean(table: dict[str, Any], key: str, default: bool) -> bool:
    """문자열 변환 없이 TOML의 실제 불리언 값만 허용한다."""
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} 설정은 true 또는 false여야 합니다.")
    return value


def _resolve_config_file(
    config_file: Path | None,
    current_directory: Path,
) -> Path | None:
    """명시적 설정 파일 또는 현재 폴더의 기본 설정 파일을 결정한다."""
    if config_file is not None:
        resolved = config_file.expanduser().resolve()
        if not resolved.is_file():
            raise ConfigError(f"설정 파일을 찾을 수 없습니다: {resolved}")
        return resolved

    candidate = current_directory / DEFAULT_CONFIG_NAME
    return candidate.resolve() if candidate.is_file() else None


def load_config(
    config_file: Path | None = None,
    *,
    current_directory: Path | None = None,
) -> AppConfig:
    """TOML 설정을 기본값 위에 적용하고 모든 값을 검증한다.

    상대 작업공간은 설정 파일이 있으면 그 파일의 부모 폴더를, 설정 파일이
    없으면 현재 작업 폴더를 기준으로 해석한다. 따라서 어느 위치에서 CLI를
    실행하더라도 같은 설정 파일은 항상 같은 작업공간을 가리킨다.
    """
    cwd = (current_directory or Path.cwd()).expanduser().resolve()
    source_file = _resolve_config_file(config_file, cwd)
    data: dict[str, Any] = {}

    if source_file is not None:
        try:
            with source_file.open("rb") as stream:
                parsed = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ConfigError(
                f"설정 파일을 읽을 수 없습니다: {source_file}: {error}"
            ) from error
        data = parsed

    ansys_table = _table(data, "ansys")
    agent_table = _table(data, "agent")
    workspace_table = _table(data, "workspace")

    ansys = AnsysConfig(
        version=_string(ansys_table, "version", "261"),
        workbench_port=_integer(
            ansys_table,
            "workbench_port",
            50055,
            minimum=1,
            maximum=65535,
        ),
        headless=_boolean(ansys_table, "headless", False),
    )
    agent = AgentConfig(
        provider=_string(agent_table, "provider", "codex"),
        max_retries=_integer(
            agent_table,
            "max_retries",
            3,
            minimum=0,
            maximum=10,
        ),
    )

    root_value = _string(workspace_table, "root", "workspace")
    root = Path(root_value).expanduser()
    base_directory = source_file.parent if source_file is not None else cwd
    if not root.is_absolute():
        root = base_directory / root

    return AppConfig(
        ansys=ansys,
        agent=agent,
        workspace=WorkspaceConfig(root=root.resolve()),
        source_file=source_file,
    )


def prepare_workspace(config: WorkspaceConfig) -> None:
    """정해진 작업공간 폴더만 생성하고 기존 파일은 변경하지 않는다."""
    for directory in config.directories():
        directory.mkdir(parents=True, exist_ok=True)


def render_config_text(config: AppConfig) -> str:
    """터미널에서 빠르게 확인할 수 있는 설정 요약을 만든다."""
    source = str(config.source_file) if config.source_file else "기본값"
    return "\n".join(
        (
            f"설정 출처: {source}",
            f"Ansys 버전: {config.ansys.version}",
            f"Workbench 포트: {config.ansys.workbench_port}",
            f"Headless 실행: {config.ansys.headless}",
            f"AI 제공자: {config.agent.provider}",
            f"최대 재시도: {config.agent.max_retries}",
            f"작업공간: {config.workspace.root}",
        )
    )


def render_config_json(config: AppConfig) -> str:
    """민감정보가 포함되지 않은 설정을 JSON으로 직렬화한다."""
    return json.dumps(config.to_dict(), ensure_ascii=False, indent=2)
