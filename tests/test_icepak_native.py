"""실제 AEDT 없이 Native ScriptEnv 런타임 선택과 수명주기를 검증한다."""

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from cae_agent.ansys.icepak import IcepakError
from cae_agent.ansys.icepak_native import (
    NativeIcepakRuntime,
    native_installed_aedt_versions,
    resolve_native_runtime,
    run_native_icepak_script,
    validate_native_hostname,
)
from cae_agent.core.config import load_config


def _runtime(tmp_path: Path) -> NativeIcepakRuntime:
    root = tmp_path / "AnsysEM"
    desktop = root / "ansysedtsv.exe"
    python = root / "commonfiles/CPython/3_10/winx64/Release/python/python.exe"
    plugin = root / "PythonFiles/DesktopPlugin"
    for path in (desktop, python):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    plugin.mkdir(parents=True)
    return NativeIcepakRuntime("2025.2", root, desktop, python, plugin)


def test_runtime_is_derived_from_student_installation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    selected = resolve_native_runtime(
        load_config(current_directory=tmp_path),
        student_version=True,
        installed={"2025.2SV": str(runtime.root)},
    )

    assert selected.desktop.name == "ansysedtsv.exe"
    assert selected.python == runtime.python
    assert selected.plugin == runtime.plugin


def test_native_installation_discovery_does_not_require_pyaedt(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    assert native_installed_aedt_versions(
        {"ANSYSEM_ROOT252": str(runtime.root)}
    ) == {"2025.2SV": str(runtime.root.resolve())}


def test_non_ascii_hostname_is_rejected_before_aedt_launch() -> None:
    with pytest.raises(IcepakError, match="ASCII"):
        validate_native_hostname("민우-PC")


class FakeProcess:
    """실행기가 시작한 AEDT 프로세스만 회수하는지 기록하는 테스트 대역이다."""

    returncode = None
    terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_native_run_stages_payload_checks_marker_and_stops_aedt(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    script = tmp_path / "probe.py"
    script.write_text("result = oDesktop.GetVersion()\n", encoding="utf-8")
    process = FakeProcess()
    launched: list[list[str]] = []

    def popen(command, **_kwargs):
        launched.append(command)
        return process

    result = run_native_icepak_script(
        config,
        script,
        student_version=True,
        runtime=_runtime(tmp_path),
        hostname="MINWOO",
        run_id_factory=lambda: "fixed",
        port_factory=lambda: 50001,
        popen_factory=popen,
        waiter=lambda *_args: None,
        runner=lambda *_args, **_kwargs: CompletedProcess(
            [], 0, "AEDT message\nCAE_NATIVE_RESULT=\"2025.2\"\n", ""
        ),
    )

    assert result.return_value == "2025.2"
    assert Path(result.staged_script).read_text(encoding="utf-8").startswith("result")
    assert launched[0][-2:] == ["-grpcsrv", "50001"]
    assert process.terminated is True


def test_native_run_rejects_missing_success_marker_and_stops_aedt(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    script = tmp_path / "probe.py"
    script.write_text("result = 'ok'\n", encoding="utf-8")
    process = FakeProcess()

    with pytest.raises(IcepakError, match="성공 결과 마커"):
        run_native_icepak_script(
            config,
            script,
            runtime=_runtime(tmp_path),
            hostname="MINWOO",
            run_id_factory=lambda: "missing-marker",
            popen_factory=lambda *_args, **_kwargs: process,
            waiter=lambda *_args: None,
            runner=lambda *_args, **_kwargs: CompletedProcess([], 0, "done", ""),
        )
    assert process.terminated is True
