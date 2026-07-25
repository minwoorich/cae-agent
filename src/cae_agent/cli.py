"""CAE Agent의 최상위 명령행 인터페이스를 정의한다.

이 모듈은 사용자가 실행하는 모든 하위 명령의 시작점이다. 현재 초기 버전에는
도움말과 버전 출력만 포함되어 있으며, 이후 ``doctor``, ``workbench``,
``spaceclaim``, ``mechanical`` 명령을 이 파서 아래에 단계적으로 추가한다.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from cae_agent import __version__


def build_parser() -> argparse.ArgumentParser:
    """CAE Agent에서 공통으로 사용하는 최상위 인자 파서를 생성한다.

    파서 생성을 ``main`` 함수와 분리하여 테스트에서 운영체제 프로세스를 새로
    실행하지 않고도 옵션과 도움말을 검증할 수 있게 한다.
    """
    parser = argparse.ArgumentParser(
        prog="cae-agent",
        description=(
            "AI-assisted automation for Ansys SpaceClaim and Mechanical."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """전달된 인자를 해석하여 CAE Agent 명령을 실행한다.

    Args:
        argv: 해석할 명령행 인자 목록이다. ``None``이면 ``argparse``가 실제
            프로세스 인자를 읽으며, 테스트에서는 별도의 목록을 전달할 수 있다.

    Returns:
        명령이 정상적으로 처리되면 운영체제 성공 종료 코드인 ``0``을 반환한다.
    """
    parser = build_parser()
    parser.parse_args(argv)
    return 0
