"""AEDT 내장 CPython과 ScriptEnv를 사용하는 Icepak 네이티브 실행기다.

PyAEDT 연결이 로컬 보안 정책이나 gRPC 초기화 단계에서 멈추는 환경을 위해,
설치본에 포함된 공식 DesktopPlugin을 직접 사용한다. 실행기는 자신이 시작한
AEDT 프로세스만 종료하며 사용자 프로젝트와 원본 스크립트는 수정하지 않는다.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping

from cae_agent.ansys.icepak import IcepakError, installed_aedt_versions, select_aedt_version
from cae_agent.core.config import AppConfig


SUCCESS_MARKER = "CAE_NATIVE_RESULT="
AEDT_MESSAGE_MARKER = "CAE_NATIVE_AEDT_MESSAGES="


@dataclass(frozen=True, slots=True)
class NativeIcepakRuntime:
    """선택한 AEDT 설치본에서 확인한 네이티브 실행 파일 묶음이다."""

    version: str
    root: Path
    desktop: Path
    python: Path
    plugin: Path


@dataclass(frozen=True, slots=True)
class NativeIcepakResult:
    """재현 가능한 네이티브 실행 위치와 검증된 반환값을 기록한다."""

    run_id: str
    status: str
    version: str
    staged_script: str
    return_value: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def native_box_attributes(name: str, material: str) -> list[object]:
    """AEDT 2025 R2 Native gRPC에서 검증된 최소 CreateBox 속성을 만든다.

    GUI 녹화 매크로의 ``UDMId``, ``IsMaterialEditable``과 ``IsLightweight`` 같은
    확장 속성은 DesktopPlugin 경로에서 ``0x80020009``를 유발할 수 있다. 색상과
    투명도는 형상 생성 후 별도 속성 변경으로 적용하고 생성 호출은 최소화한다.
    """
    clean_name = name.strip()
    clean_material = material.strip()
    if not clean_name or not clean_material:
        raise IcepakError("Native CreateBox에는 이름과 재료가 모두 필요합니다.")
    return [
        "NAME:Attributes",
        "Name:=",
        clean_name,
        "MaterialValue:=",
        f'"{clean_material}"',
        "SolveInside:=",
        True,
    ]


def native_installed_aedt_versions(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """ANSYSEM_ROOT 환경 변수에서 PyAEDT 없이 AEDT 설치본을 탐색한다."""
    active_environ = environ if environ is not None else os.environ
    versions: dict[str, str] = {}
    for name, value in active_environ.items():
        prefix = "ANSYSEM_ROOT"
        suffix = name[len(prefix) :] if name.upper().startswith(prefix) else ""
        if len(suffix) != 3 or not suffix.isdigit():
            continue
        version = f"20{suffix[:2]}.{suffix[2]}"
        root = Path(value).resolve()
        key = version + ("SV" if (root / "ansysedtsv.exe").is_file() else "")
        versions[key] = str(root)
    return versions


def resolve_native_runtime(
    config: AppConfig,
    *,
    student_version: bool,
    aedt_version: str | None = None,
    installed: Mapping[str, str] | None = None,
) -> NativeIcepakRuntime:
    """AEDT 루트에서 Desktop, 내장 Python과 DesktopPlugin을 모두 검증한다."""
    if installed is not None:
        versions = dict(installed)
    else:
        versions = native_installed_aedt_versions()
        if not versions:
            versions = installed_aedt_versions()
    version = select_aedt_version(
        config.ansys.version,
        student_version=student_version,
        explicit_version=aedt_version,
        installed=versions,
    )
    keys = [version + ("SV" if student_version else ""), version]
    root_value = next((versions[key] for key in keys if key in versions), None)
    if root_value is None:
        kind = "Student" if student_version else "일반"
        raise IcepakError(f"AEDT {kind} {version} 설치 경로를 찾을 수 없습니다.")
    root = Path(root_value).resolve()
    desktop = root / ("ansysedtsv.exe" if student_version else "ansysedt.exe")
    python = root / "commonfiles" / "CPython" / "3_10" / "winx64" / "Release" / "python" / "python.exe"
    plugin = root / "PythonFiles" / "DesktopPlugin"
    missing = [path for path in (desktop, python, plugin) if not path.exists()]
    if missing:
        raise IcepakError("AEDT 네이티브 런타임 구성요소가 없습니다: " + ", ".join(map(str, missing)))
    return NativeIcepakRuntime(version, root, desktop, python, plugin)


def validate_native_hostname(hostname: str | None = None) -> str:
    """ScriptEnv gRPC가 처리하지 못하는 비 ASCII 컴퓨터 이름을 미리 차단한다."""
    value = hostname or socket.gethostname()
    if not value.isascii():
        raise IcepakError(
            "Native ScriptEnv 실행에는 ASCII 컴퓨터 이름이 필요합니다. "
            f"현재 이름: {value}"
        )
    return value


def _free_local_port() -> int:
    """외부 인터페이스에 노출하지 않고 localhost의 임시 포트를 선택한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[str], timeout: float) -> None:
    """AEDT 조기 종료를 감지하면서 gRPC 리스너가 준비될 때까지 기다린다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IcepakError(f"AEDT가 gRPC 준비 전에 종료되었습니다(코드 {process.returncode}).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise IcepakError(f"AEDT gRPC 포트 {port}가 {timeout:g}초 안에 준비되지 않았습니다.")


def _wrapper_source() -> str:
    """ScriptEnv가 주입한 oDesktop을 사용자 스크립트에 전달하는 고정 래퍼다."""
    return '''import json\nimport sys\nimport traceback\nplugin, port, payload = sys.argv[1], int(sys.argv[2]), sys.argv[3]\nsys.path.insert(0, plugin)\nimport ScriptEnv\nScriptEnv.Initialize("", False, "", port)\nnamespace = {"__name__": "__cae_agent_icepak_native__", "oDesktop": oDesktop}\ntry:\n    with open(payload, "r", encoding="utf-8-sig") as stream:\n        source = stream.read()\n    exec(compile(source, payload, "exec"), namespace, namespace)\n    print("CAE_NATIVE_RESULT=" + json.dumps(str(namespace.get("result", "")), ensure_ascii=False), flush=True)\nexcept Exception:\n    try:\n        messages = list(oDesktop.GetMessages("", "", 0))\n    except Exception as message_error:\n        messages = ["AEDT 메시지 조회 실패: " + str(message_error)]\n    print("CAE_NATIVE_AEDT_MESSAGES=" + json.dumps(messages, ensure_ascii=False), file=sys.stderr, flush=True)\n    traceback.print_exc(file=sys.stderr)\n    raise\nfinally:\n    ScriptEnv.Shutdown()\n'''


def _native_failure_detail(stdout: str, stderr: str) -> str:
    """긴 traceback에 앞선 AEDT 메시지 마커를 잃지 않도록 오류를 요약한다."""
    raw_detail = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    message_line = next(
        (line for line in raw_detail.splitlines() if line.startswith(AEDT_MESSAGE_MARKER)),
        "",
    )
    tail = raw_detail[-2000:]
    return "\n".join(part for part in (message_line, tail) if part)


def run_native_icepak_script(
    config: AppConfig,
    script_file: Path,
    *,
    student_version: bool = False,
    aedt_version: str | None = None,
    timeout: float = 120.0,
    runtime: NativeIcepakRuntime | None = None,
    hostname: str | None = None,
    run_id_factory: Callable[[], str] | None = None,
    port_factory: Callable[[], int] | None = None,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    waiter: Callable[[int, subprocess.Popen[str], float], None] = _wait_for_port,
) -> NativeIcepakResult:
    """새 AEDT gRPC 세션에서 스테이징된 스크립트를 실행하고 성공 마커를 검증한다."""
    validate_native_hostname(hostname)
    active_runtime = runtime or resolve_native_runtime(
        config, student_version=student_version, aedt_version=aedt_version
    )
    source = script_file.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".py":
        raise IcepakError(f"실행할 .py Icepak 스크립트를 찾을 수 없습니다: {source}")
    run_id = (run_id_factory or (lambda: uuid.uuid4().hex))()
    run_dir = config.workspace.generated_dir.resolve() / "icepak" / "native" / run_id
    if run_dir.exists():
        raise IcepakError(f"기존 네이티브 실행 폴더를 덮어쓸 수 없습니다: {run_dir}")
    run_dir.mkdir(parents=True)
    staged = run_dir / source.name
    staged.write_bytes(source.read_bytes())
    wrapper = run_dir / "runner.py"
    wrapper.write_text(_wrapper_source(), encoding="utf-8")
    port = (port_factory or _free_local_port)()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = popen_factory(
        [str(active_runtime.desktop), "-grpcsrv", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=flags,
    )
    try:
        waiter(port, process, min(timeout, 60.0))
        completed = runner(
            [str(active_runtime.python), str(wrapper), str(active_runtime.plugin), str(port), str(staged)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if completed.returncode != 0:
            detail = _native_failure_detail(completed.stdout, completed.stderr)
            raise IcepakError(f"Native ScriptEnv 실행 실패(코드 {completed.returncode}): {detail}")
        marker_line = next(
            (line for line in completed.stdout.splitlines() if line.startswith(SUCCESS_MARKER)),
            None,
        )
        if marker_line is None:
            detail = _native_failure_detail(completed.stdout, completed.stderr)
            raise IcepakError(
                "Native ScriptEnv가 성공 결과 마커를 반환하지 않았습니다. "
                f"출력: {detail or '(없음)'}"
            )
        return_value = json.loads(marker_line[len(SUCCESS_MARKER) :])
        return NativeIcepakResult(run_id, "success", active_runtime.version, str(staged), return_value)
    except subprocess.TimeoutExpired as error:
        raise IcepakError(f"Native ScriptEnv 실행이 {timeout:g}초를 초과했습니다.") from error
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
