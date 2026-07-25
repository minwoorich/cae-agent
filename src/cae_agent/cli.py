"""CAE Agent의 최상위 명령행 인터페이스를 정의한다.

이 모듈은 사용자가 실행하는 모든 하위 명령의 시작점이다. 현재 초기 버전에는
도움말과 버전 출력만 포함되어 있으며, 이후 ``doctor``, ``workbench``,
``spaceclaim``, ``mechanical`` 명령을 이 파서 아래에 단계적으로 추가한다.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from cae_agent import __version__
from cae_agent.doctor import CheckStatus, render_json, render_text, run_checks


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

    subparsers = parser.add_subparsers(dest="command")
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Python, Ansys 및 AI CLI 실행 환경을 진단합니다.",
        description=(
            "프로그램을 설치하거나 Ansys를 실행하지 않고 CAE Agent의 "
            "필수 구성요소와 권장 도구를 확인합니다."
        ),
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="진단 결과를 자동화용 JSON 형식으로 출력합니다.",
    )
    doctor_parser.add_argument(
        "--workspace",
        type=Path,
        default=Path("workspace"),
        help="쓰기 가능 여부를 검사할 작업공간 경로입니다.",
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
    args = parser.parse_args(argv)

    if args.command == "doctor":
        results = run_checks(args.workspace)
        output = (
            render_json(results) if args.json_output else render_text(results)
        )
        print(output)
        # 필수 진단이 하나라도 실패하면 셸과 설치 스크립트가 문제를 감지할 수
        # 있도록 0이 아닌 종료 코드를 반환한다. WARN은 실행을 막지 않는다.
        return int(
            any(result.status is CheckStatus.FAIL for result in results)
        )

    return 0
