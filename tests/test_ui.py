"""NiceGUI 선택 의존성과 로컬 대시보드의 읽기·승인 경계를 검증한다."""

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from cae_agent.config import load_config, prepare_workspace
from cae_agent.doctor import CheckResult, CheckStatus
from cae_agent.ui import UIError, dashboard_snapshot, launch_ui


def test_dashboard_snapshot_reads_status_without_model_changes(
    tmp_path: Path,
) -> None:
    """대시보드 스냅숏은 파일과 세션 메타데이터만 읽어 요약해야 한다."""
    config = load_config(current_directory=tmp_path)
    prepare_workspace(config.workspace)
    (config.workspace.logs_dir / "latest.log").write_text(
        "log",
        encoding="utf-8",
    )
    (config.workspace.results_dir / "model.wbpj").write_text(
        "result",
        encoding="utf-8",
    )

    snapshot = dashboard_snapshot(
        config,
        checker=lambda _root: [
            CheckResult("python", CheckStatus.PASS, "Python 정상")
        ],
    )

    assert snapshot.checks[0].status is CheckStatus.PASS
    assert snapshot.workbench_session is False
    assert snapshot.mechanical_session_count == 0
    assert snapshot.recent_logs == ("latest.log",)
    assert snapshot.recent_results == ("model.wbpj",)
    assert snapshot.workspace.total_file_count == 2


def test_launch_ui_uses_localhost_and_requested_browser_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대시보드는 외부 주소가 아니라 고정된 localhost에만 바인딩해야 한다."""
    config = load_config(current_directory=tmp_path)
    calls: dict[str, object] = {}
    def fake_run(**kwargs) -> None:
        calls.update(kwargs)
        kwargs["root"]()

    fake_ui = SimpleNamespace(run=fake_run)
    monkeypatch.setattr(
        "cae_agent.ui.build_dashboard",
        lambda _config, *, ui_module: calls.update({"built": ui_module}),
    )

    launch_ui(config, port=9876, show=False, ui_module=fake_ui)

    assert calls["built"] is fake_ui
    assert callable(calls["root"])
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 9876
    assert calls["show"] is False
    assert calls["reload"] is False


@pytest.mark.parametrize("port", [0, 65536])
def test_launch_ui_rejects_invalid_port(tmp_path: Path, port: int) -> None:
    """잘못된 포트는 NiceGUI import나 서버 시작 전에 거부해야 한다."""
    config = load_config(current_directory=tmp_path)

    with pytest.raises(UIError, match="1~65535"):
        launch_ui(config, port=port, ui_module=SimpleNamespace())


def test_ui_source_keeps_preview_and_approval_separate() -> None:
    """UI 코드가 dry-run과 실제 삭제를 서로 다른 사용자 동작으로 유지해야 한다."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cae_agent"
        / "ui.py"
    ).read_text(encoding="utf-8")

    assert "def preview_cleanup()" in source
    assert "approve=False" in source
    assert "def execute_cleanup()" in source
    assert "approve=True" in source
    assert "preview_paths != current_paths" in source
    assert 'host="127.0.0.1"' in source
    assert "input과 results는 삭제하지 않습니다" in source


def test_missing_nicegui_reports_optional_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI 선택 의존성이 없어도 import가 가능하고 실행 시 설치법을 안내해야 한다."""
    config = load_config(current_directory=tmp_path)
    original_import = builtins.__import__

    def fail_nicegui(name, *args, **kwargs):
        if name == "nicegui":
            raise ImportError("테스트용 NiceGUI 누락")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_nicegui)
    with pytest.raises(UIError, match=r"\.\[ui\]"):
        launch_ui(config)
