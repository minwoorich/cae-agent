"""AI 제공자가 공통으로 반환해야 하는 결과와 오류를 정의한다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


class AgentError(RuntimeError):
    """AI 제공자 호출 또는 생성 결과 검증에 실패했을 때의 오류."""


@dataclass(frozen=True, slots=True)
class GeneratedScript:
    """검증 후 작업공간에 보존된 CAE 스크립트 생성 결과."""

    run_id: str
    provider: str
    target: str
    script_file: str
    metadata_file: str
    explanation: str
    assumptions: tuple[str, ...]

    def to_json(self) -> str:
        """CLI와 후속 자동화가 사용할 JSON 문자열을 반환한다."""
        payload = asdict(self)
        payload["assumptions"] = list(self.assumptions)
        return json.dumps(payload, ensure_ascii=False, indent=2)
