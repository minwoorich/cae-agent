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
from cae_agent.config import (
    DEFAULT_CONFIG_NAME,
    ConfigError,
    load_config,
    prepare_workspace,
    render_config_json,
    render_config_text,
)
from cae_agent.doctor import CheckStatus, render_json, render_text, run_checks
from cae_agent.mechanical import (
    MechanicalError,
    connect_mechanical,
    mechanical_status,
    run_mechanical_script,
    start_mechanical_session,
)
from cae_agent.project import ProjectError, create_project
from cae_agent.spaceclaim import SpaceClaimError, run_spaceclaim_script
from cae_agent.workbench import (
    WorkbenchError,
    connect_session,
    load_session,
    ping_session,
    request_stop,
    run_script,
    serve_session,
    workbench_paths,
)


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

    config_parser = subparsers.add_parser(
        "config",
        help="CAE Agent 설정을 확인하고 작업공간을 준비합니다.",
    )
    config_subparsers = config_parser.add_subparsers(
        dest="config_command",
        required=True,
    )
    config_show_parser = config_subparsers.add_parser(
        "show",
        help="검증된 최종 설정값을 출력합니다.",
    )
    config_show_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    config_show_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="설정을 자동화용 JSON 형식으로 출력합니다.",
    )
    config_show_parser.add_argument(
        "--prepare",
        action="store_true",
        help="출력 전에 정의된 작업공간 폴더를 생성합니다.",
    )

    workbench_parser = subparsers.add_parser(
        "workbench",
        help="로컬 Ansys Workbench 세션을 실행하고 제어합니다.",
    )
    workbench_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    workbench_subparsers = workbench_parser.add_subparsers(
        dest="workbench_command",
        required=True,
    )
    workbench_subparsers.add_parser(
        "start",
        help="Workbench 세션을 시작하고 현재 터미널에서 유지합니다.",
    )
    workbench_subparsers.add_parser(
        "status",
        help="저장된 세션에 연결해 응답 상태를 확인합니다.",
    )
    workbench_subparsers.add_parser(
        "stop",
        help="실행 중인 브리지에 정상 종료를 요청합니다.",
    )
    create_project_parser = workbench_subparsers.add_parser(
        "create-project",
        help="새 해석 시스템을 만들고 Workbench 프로젝트를 저장합니다.",
    )
    create_project_parser.add_argument(
        "--template",
        default="Steady-State Thermal",
        dest="template_name",
        help="Workbench 해석 템플릿 이름입니다.",
    )
    create_project_parser.add_argument(
        "--solver",
        default="ANSYS",
        help="템플릿에 사용할 solver 이름입니다.",
    )
    create_project_parser.add_argument(
        "--output",
        type=Path,
        help="작업공간 내부의 프로젝트 출력 경로입니다.",
    )
    create_project_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 프로젝트와 연결 데이터가 있어도 덮어씁니다.",
    )
    run_parser = workbench_subparsers.add_parser(
        "run-script",
        help="현재 세션에서 Workbench 저널 파일을 실행합니다.",
    )
    run_parser.add_argument("script_file", type=Path)

    spaceclaim_parser = subparsers.add_parser(
        "spaceclaim",
        help="Workbench Geometry 셀에서 SpaceClaim 스크립트를 실행합니다.",
    )
    spaceclaim_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    spaceclaim_subparsers = spaceclaim_parser.add_subparsers(
        dest="spaceclaim_command",
        required=True,
    )
    spaceclaim_run_parser = spaceclaim_subparsers.add_parser(
        "run",
        help="Python 스크립트를 지정한 Geometry 셀에서 실행합니다.",
    )
    spaceclaim_run_parser.add_argument("script_file", type=Path)
    spaceclaim_run_parser.add_argument(
        "--system-name",
        default="SYS",
        help="대상 Workbench 시스템 이름입니다. 기본값: SYS",
    )
    spaceclaim_run_parser.add_argument(
        "--clear",
        action="store_true",
        dest="clear_geometry",
        help="스크립트 실행 전에 기존 SpaceClaim 형상을 모두 제거합니다.",
    )

    mechanical_parser = subparsers.add_parser(
        "mechanical",
        help="Workbench 시스템의 Mechanical 서버와 스크립트를 제어합니다.",
    )
    mechanical_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    mechanical_parser.add_argument(
        "--system-name",
        default="SYS",
        help="대상 Workbench 시스템 이름입니다. 기본값: SYS",
    )
    mechanical_subparsers = mechanical_parser.add_subparsers(
        dest="mechanical_command",
        required=True,
    )
    mechanical_subparsers.add_parser(
        "connect",
        help="Workbench에서 Mechanical 서버를 시작하고 연결합니다.",
    )
    mechanical_subparsers.add_parser(
        "status",
        help="저장된 Mechanical 세션의 응답 상태를 확인합니다.",
    )
    mechanical_run_parser = mechanical_subparsers.add_parser(
        "run-script",
        help="Mechanical 내부 Python에서 스크립트를 실행합니다.",
    )
    mechanical_run_parser.add_argument("script_file", type=Path)
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

    if args.command == "config" and args.config_command == "show":
        try:
            config = load_config(args.config_file)
            if args.prepare:
                prepare_workspace(config.workspace)
        except (ConfigError, OSError) as error:
            parser.error(str(error))
        print(
            render_config_json(config)
            if args.json_output
            else render_config_text(config)
        )
        return 0

    if args.command == "workbench":
        try:
            config = load_config(args.config_file)
            if args.workbench_command == "start":
                serve_session(config)
                return 0
            if args.workbench_command == "status":
                # 먼저 세션 파일 자체를 검증하면 손상된 메타데이터와 실제 연결
                # 실패를 사용자가 구분할 수 있다.
                session = load_session(workbench_paths(config).session_file)
                result = ping_session(connect_session(config))
                print(
                    f"Workbench {session.server_version} 응답: {result}"
                )
                return 0
            if args.workbench_command == "stop":
                print(f"종료 요청 생성: {request_stop(config)}")
                return 0
            if args.workbench_command == "create-project":
                result = create_project(
                    config,
                    template_name=args.template_name,
                    solver=args.solver,
                    output=args.output,
                    overwrite=args.overwrite,
                )
                print(result.to_json())
                return 0
            if args.workbench_command == "run-script":
                print(run_script(config, args.script_file))
                return 0
        except (
            ConfigError,
            ProjectError,
            WorkbenchError,
            OSError,
        ) as error:
            parser.error(str(error))

    if args.command == "spaceclaim" and args.spaceclaim_command == "run":
        try:
            config = load_config(args.config_file)
            result = run_spaceclaim_script(
                config,
                args.script_file,
                system_name=args.system_name,
                clear_geometry=args.clear_geometry,
            )
        except (ConfigError, WorkbenchError, SpaceClaimError, OSError) as error:
            parser.error(str(error))
        print(result.to_json())
        return 0

    if args.command == "mechanical":
        try:
            config = load_config(args.config_file)
            if args.mechanical_command == "connect":
                session, status = start_mechanical_session(
                    config,
                    system_name=args.system_name,
                )
                print(
                    json.dumps(
                        {
                            "host": session.host,
                            "port": session.port,
                            "system_name": session.system_name,
                            "status": status,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.mechanical_command == "status":
                active = connect_mechanical(
                    config,
                    system_name=args.system_name,
                )
                print(mechanical_status(active))
                return 0
            if args.mechanical_command == "run-script":
                result = run_mechanical_script(
                    config,
                    args.script_file,
                    system_name=args.system_name,
                )
                print(result.to_json())
                return 0
        except (ConfigError, MechanicalError, WorkbenchError, OSError) as error:
            parser.error(str(error))

    return 0
