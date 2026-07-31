"""CAE Agent의 최상위 명령행 인터페이스를 정의한다.

이 모듈은 사용자가 실행하는 모든 하위 명령의 시작점이다. 현재 초기 버전에는
도움말과 버전 출력만 포함되어 있으며, 이후 ``doctor``, ``workbench``,
``spaceclaim``, ``mechanical`` 명령을 이 파서 아래에 단계적으로 추가한다.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cae_agent import __version__
from cae_agent.agent.providers import AgentError, CodexProvider
from cae_agent.core.config import (
    DEFAULT_CONFIG_NAME,
    ConfigError,
    load_config,
    prepare_workspace,
    render_config_json,
    render_config_text,
)
from cae_agent.core.doctor import CheckStatus, render_json, render_text, run_checks
from cae_agent.ansys.mechanical import (
    MechanicalError,
    connect_mechanical,
    mechanical_status,
    run_mechanical_script,
    start_mechanical_session,
)
from cae_agent.ansys.icepak import (
    IcepakError,
    connect_icepak,
    icepak_status,
    run_icepak_script,
)
from cae_agent.ansys.project import ProjectError, create_project
from cae_agent.agent.repair import RepairError, run_repair_loop
from cae_agent.ansys.spaceclaim import SpaceClaimError, run_spaceclaim_script
from cae_agent.ui import UIError, launch_ui
from cae_agent.ansys.workbench import (
    WorkbenchError,
    connect_session,
    load_session,
    ping_session,
    request_stop,
    run_script,
    serve_session,
    workbench_paths,
)
from cae_agent.core.workspace import (
    WorkspaceError,
    clean_workspace,
    render_cleanup_result,
    render_workspace_status,
    workspace_status,
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

    workspace_parser = subparsers.add_parser(
        "workspace",
        help="작업공간 사용량을 확인하고 오래된 안전 산출물을 정리합니다.",
    )
    workspace_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    workspace_subparsers = workspace_parser.add_subparsers(
        dest="workspace_command",
        required=True,
    )
    workspace_status_parser = workspace_subparsers.add_parser(
        "status",
        help="폴더별 파일 수, 사용량과 세션 메타데이터를 조회합니다.",
    )
    workspace_status_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="작업공간 상태를 자동화용 JSON 형식으로 출력합니다.",
    )
    workspace_clean_parser = workspace_subparsers.add_parser(
        "clean",
        help="오래된 생성본·로그·Codex 임시 파일의 정리 후보를 계산합니다.",
        description=(
            "기본 동작은 파일을 변경하지 않는 dry-run입니다. input과 results는 "
            "항상 제외되며 실제 삭제에는 --approve가 필요합니다."
        ),
    )
    workspace_clean_parser.add_argument(
        "--older-than",
        type=int,
        default=30,
        metavar="DAYS",
        help="수정 후 지정 일수가 지난 파일만 후보로 선택합니다. 기본값: 30",
    )
    workspace_clean_parser.add_argument(
        "--approve",
        action="store_true",
        help="표시된 안전 후보를 실제로 삭제하는 데 명시적으로 동의합니다.",
    )
    workspace_clean_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="정리 계획 또는 결과를 자동화용 JSON 형식으로 출력합니다.",
    )

    ui_parser = subparsers.add_parser(
        "ui",
        help="환경·세션·작업공간을 확인하는 로컬 대시보드를 실행합니다.",
        description=(
            "NiceGUI 대시보드를 127.0.0.1에서만 실행합니다. UI 로딩만으로 "
            "Ansys 모델을 변경하지 않습니다."
        ),
    )
    ui_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    ui_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="localhost 대시보드 포트입니다. 기본값: 8765",
    )
    ui_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="서버 시작 후 기본 브라우저를 자동으로 열지 않습니다.",
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

    icepak_parser = subparsers.add_parser(
        "icepak",
        help="PyAEDT를 통해 Ansys Icepak 프로젝트와 스크립트를 제어합니다.",
    )
    icepak_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    icepak_parser.add_argument(
        "--project",
        type=Path,
        required=True,
        dest="project_file",
        help="연결할 기존 .aedt 또는 .aedtz 프로젝트입니다.",
    )
    icepak_parser.add_argument(
        "--design",
        dest="design_name",
        help="선택할 Icepak 설계 이름입니다.",
    )
    icepak_parser.add_argument(
        "--new-desktop",
        action="store_true",
        help="기존 AEDT 세션 대신 새 Electronics Desktop 세션을 시작합니다.",
    )
    icepak_parser.add_argument(
        "--student-version",
        action="store_true",
        help="AEDT Student 버전으로 연결합니다.",
    )
    icepak_subparsers = icepak_parser.add_subparsers(
        dest="icepak_command",
        required=True,
    )
    icepak_subparsers.add_parser(
        "status",
        help="프로젝트와 활성 Icepak 설계의 연결 상태를 확인합니다.",
    )
    icepak_run_parser = icepak_subparsers.add_parser(
        "run-script",
        help="PyAEDT Icepak 객체가 주입된 환경에서 Python 스크립트를 실행합니다.",
    )
    icepak_run_parser.add_argument("script_file", type=Path)

    generate_parser = subparsers.add_parser(
        "generate",
        help="AI 제공자로 SpaceClaim 또는 Mechanical 스크립트를 생성합니다.",
    )
    generate_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    generate_parser.add_argument(
        "--target",
        required=True,
        choices=("spaceclaim", "mechanical", "icepak"),
        help="생성할 스크립트의 CAE 실행 환경입니다.",
    )
    prompt_group = generate_parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument(
        "--prompt",
        help="Codex에 전달할 CAE 스크립트 요구사항입니다.",
    )
    prompt_group.add_argument(
        "--prompt-file",
        type=Path,
        help="UTF-8 요구사항이 저장된 텍스트 파일입니다.",
    )

    run_agent_parser = subparsers.add_parser(
        "run-agent",
        help="AI 스크립트를 실행하고 실패 시 제한적으로 수정합니다.",
        description=(
            "이미 준비된 Workbench 또는 Mechanical 세션에서 AI 생성 코드를 "
            "실행합니다. 명시적 실행 승인 없이는 Ansys에 코드를 전달하지 않습니다."
        ),
    )
    run_agent_parser.add_argument(
        "--file",
        type=Path,
        dest="config_file",
        help=f"사용할 TOML 설정 파일입니다. 기본값: {DEFAULT_CONFIG_NAME}",
    )
    run_agent_parser.add_argument(
        "--target",
        required=True,
        choices=("spaceclaim", "mechanical"),
        help="생성·실행·수정할 CAE 실행 환경입니다.",
    )
    run_agent_parser.add_argument(
        "--system-name",
        default="SYS",
        help="이미 준비된 Workbench 시스템 이름입니다. 기본값: SYS",
    )
    run_agent_parser.add_argument(
        "--approve-execution",
        action="store_true",
        help="AI 생성 코드를 Ansys 내부에서 실행하는 데 명시적으로 동의합니다.",
    )
    run_agent_parser.add_argument(
        "--clear",
        action="store_true",
        dest="clear_geometry",
        help="SpaceClaim의 각 실행 전에 기존 형상을 모두 제거합니다.",
    )
    run_prompt_group = run_agent_parser.add_mutually_exclusive_group(
        required=True
    )
    run_prompt_group.add_argument(
        "--prompt",
        help="Codex에 전달할 CAE 자동화 요구사항입니다.",
    )
    run_prompt_group.add_argument(
        "--prompt-file",
        type=Path,
        help="UTF-8 요구사항이 저장된 텍스트 파일입니다.",
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

    if args.command == "workspace":
        try:
            config = load_config(args.config_file)
            if args.workspace_command == "status":
                result = workspace_status(config)
                print(
                    result.to_json()
                    if args.json_output
                    else render_workspace_status(result)
                )
                return 0
            if args.workspace_command == "clean":
                result = clean_workspace(
                    config,
                    older_than_days=args.older_than,
                    approve=args.approve,
                )
                print(
                    result.to_json()
                    if args.json_output
                    else render_cleanup_result(result)
                )
                return 1 if result.failures else 0
        except (ConfigError, WorkspaceError, OSError) as error:
            parser.error(str(error))

    if args.command == "ui":
        try:
            config = load_config(args.config_file)
            launch_ui(
                config,
                port=args.port,
                show=not args.no_browser,
            )
        except (ConfigError, UIError, OSError) as error:
            parser.error(str(error))
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

    if args.command == "icepak":
        try:
            config = load_config(args.config_file)
            app = connect_icepak(
                config,
                project_file=args.project_file,
                design_name=args.design_name,
                new_desktop=args.new_desktop,
                student_version=args.student_version,
            )
            if args.icepak_command == "status":
                print(icepak_status(app))
                return 0
            if args.icepak_command == "run-script":
                result = run_icepak_script(
                    config,
                    args.script_file,
                    project_file=args.project_file,
                    design_name=args.design_name,
                    new_desktop=args.new_desktop,
                    student_version=args.student_version,
                    app=app,
                )
                print(result.to_json())
                return 0
        except (ConfigError, IcepakError, OSError) as error:
            parser.error(str(error))

    if args.command == "generate":
        try:
            config = load_config(args.config_file)
            if config.agent.provider != "codex":
                raise AgentError(
                    "현재 구현된 AI 제공자는 codex뿐입니다."
                )
            request = args.prompt
            if args.prompt_file is not None:
                request = args.prompt_file.expanduser().resolve().read_text(
                    encoding="utf-8"
                )
            result = CodexProvider().generate(
                config,
                target=args.target,
                request=request,
            )
        except (AgentError, ConfigError, OSError) as error:
            parser.error(str(error))
        print(result.to_json())
        return 0

    if args.command == "run-agent":
        try:
            config = load_config(args.config_file)
            if config.agent.provider != "codex":
                raise AgentError("현재 구현된 AI 제공자는 codex뿐입니다.")
            request = args.prompt
            if args.prompt_file is not None:
                request = args.prompt_file.expanduser().resolve().read_text(
                    encoding="utf-8"
                )
            result = run_repair_loop(
                config,
                target=args.target,
                request=request,
                system_name=args.system_name,
                approve_execution=args.approve_execution,
                clear_geometry=args.clear_geometry,
            )
        except (AgentError, ConfigError, RepairError, OSError) as error:
            parser.error(str(error))
        print(result.to_json())
        return 0 if result.success else 1

    return 0
