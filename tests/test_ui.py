"""NiceGUI 선택 의존성과 로컬 대시보드의 읽기·승인 경계를 검증한다."""

import builtins
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from cae_agent.config import load_config, prepare_workspace
from cae_agent.doctor import CheckResult, CheckStatus
from cae_agent.ui import (
    UploadConflict,
    UIError,
    dashboard_snapshot,
    input_file_summaries,
    launch_ui,
    probe_workbench_connection,
    replace_input_upload,
    store_input_upload,
)


@pytest.fixture
def ui_source() -> str:
    """안전 경계와 정보 구조 테스트가 공유할 UI 원본을 한 번 읽어 반환한다."""
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "cae_agent"
        / "ui.py"
    ).read_text(encoding="utf-8")


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
    assert snapshot.recent_inputs == ()
    assert snapshot.recent_logs == ("latest.log",)
    assert snapshot.recent_results == ("model.wbpj",)
    assert snapshot.workspace.total_file_count == 2


def test_workbench_probe_does_not_treat_missing_metadata_as_connected(
    tmp_path: Path,
) -> None:
    """세션 파일이 없으면 Workbench 연결됨으로 잘못 표시하지 않아야 한다."""
    config = load_config(current_directory=tmp_path)

    result = probe_workbench_connection(config)

    assert result.connected is False
    assert result.label == "Workbench · 세션 없음"


def test_workbench_probe_requires_real_ping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실제 ping까지 성공한 경우에만 Workbench 연결됨을 반환해야 한다."""
    config = load_config(current_directory=tmp_path)
    session_file = tmp_path / "session.json"
    session_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "cae_agent.ui.workbench_paths",
        lambda _config: SimpleNamespace(session_file=session_file),
    )
    monkeypatch.setattr(
        "cae_agent.ui.load_session",
        lambda _path: SimpleNamespace(server_version="261"),
    )
    monkeypatch.setattr(
        "cae_agent.ui.connect_session",
        lambda _config: object(),
    )
    monkeypatch.setattr(
        "cae_agent.ui.ping_session",
        lambda _workbench: "project.wbpj",
    )

    result = probe_workbench_connection(config)

    assert result.connected is True
    assert result.label == "Workbench 261 · 연결됨"
    assert "project.wbpj" in result.detail


def test_input_file_summaries_return_safe_recent_metadata(
    tmp_path: Path,
) -> None:
    """입력 라이브러리는 절대 경로 없이 크기·형식·시각 메타데이터를 반환해야 한다."""
    input_directory = tmp_path / "input"
    input_directory.mkdir()
    older = input_directory / "older.step"
    newer = input_directory / "최신모델.scdoc"
    older.write_bytes(b"old")
    newer.write_bytes(b"new-data")
    older.touch()
    newer.touch()
    older_mtime = older.stat().st_mtime - 60
    os.utime(older, (older_mtime, older_mtime))

    summaries = input_file_summaries(input_directory)

    assert [item.name for item in summaries] == [
        "최신모델.scdoc",
        "older.step",
    ]
    assert summaries[0].extension == ".scdoc"
    assert summaries[0].size_bytes == 8
    assert summaries[0].modified_at.tzinfo is not None
    assert all(str(tmp_path) not in item.name for item in summaries)


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


def test_ui_source_keeps_preview_and_approval_separate(
    ui_source: str,
) -> None:
    """UI 코드가 dry-run과 실제 삭제를 서로 다른 사용자 동작으로 유지해야 한다."""
    assert "def preview_cleanup()" in ui_source
    assert "approve=False" in ui_source
    assert "def execute_cleanup()" in ui_source
    assert "approve=True" in ui_source
    assert "preview_paths != current_paths" in ui_source
    assert 'host="127.0.0.1"' in ui_source
    assert "input과 results는 삭제하지 않습니다" in ui_source
    assert 'target.open("xb")' in ui_source
    assert "store_input_upload" in ui_source
    # 업로드 이벤트는 파일 저장과 다음 메시지 첨부까지만 수행해야 한다.
    # 실행 함수가 handle_upload 내부에 추가되면 이 검사가 실패하도록 범위를 자른다.
    upload_handler = ui_source.split(
        "async def handle_upload", maxsplit=1
    )[1].split("def cancel_upload_replacement", maxsplit=1)[0]
    assert "store_input_upload" in upload_handler
    assert "selected_inputs.add" in upload_handler
    assert "stream_codex_message" not in upload_handler
    assert "cae-hidden-upload" in ui_source
    assert 'run_method("pickFiles")' in ui_source


def test_ui_source_auto_scrolls_stream_without_interrupting_history_reading(
    ui_source: str,
) -> None:
    """스트리밍 자동 스크롤이 하단 추적과 과거 대화 읽기를 함께 지원해야 한다."""
    assert "async def scroll_chat_to_latest" in ui_source
    assert "stream.dataset.autoFollow" in ui_source
    assert "isNearBottom()" in ui_source
    assert "await scroll_chat_to_latest()" in ui_source
    assert "await scroll_chat_to_latest(force=True)" in ui_source
    assert "id=cae-chat-stream" in ui_source


def test_ui_source_keeps_chat_session_during_navigation_and_shows_progress(
    ui_source: str,
) -> None:
    """같은 페이지의 메뉴 전환이 세션을 닫지 않고 공개 진행 단계를 표시해야 한다."""
    assert "progress_steps" in ui_source
    assert "ChatProgressStep" in ui_source
    assert "작업 과정" in ui_source
    assert 'event.kind == "progress"' in ui_source
    assert "ui.timer(1.0, refresh_progress_clock)" in ui_source
    # Codex 종료는 브라우저 연결 종료에만 묶고 탭 변경 이벤트에는 연결하지 않는다.
    assert "on_disconnect(codex_client.close)" in ui_source
    assert "on_change=codex_client.close" not in ui_source
    assert "CodexAppServerClient(\n        config.workspace.root," in ui_source
    assert "approval_decision(" in ui_source
    assert "보호된 경로 변경을 차단했습니다" in ui_source


def test_ui_source_submits_with_enter_and_preserves_shift_enter(
    ui_source: str,
) -> None:
    """Enter 전송은 IME 조합과 Shift+Enter 줄바꿈을 침범하지 않아야 한다."""
    assert "CHAT_SUBMIT_KEYDOWN_JS" in ui_source
    assert "event.key === 'Enter'" in ui_source
    assert "!event.shiftKey" in ui_source
    assert "!event.isComposing" in ui_source
    assert "event.keyCode !== 229" in ui_source
    assert "!event.repeat" in ui_source
    assert "event.preventDefault()" in ui_source
    assert '"keydown",' in ui_source
    assert "send_chat_message," in ui_source


def test_ui_source_defines_structured_information_architecture(
    ui_source: str,
) -> None:
    """UI가 핵심 작업을 분리한 내비게이션 구조를 유지해야 한다."""
    assert "ui.left_drawer" in ui_source
    assert '"overview"' in ui_source
    assert '"chat"' in ui_source
    assert 'ui.tab(\n                "files"' not in ui_source
    assert "LOCAL SESSION" not in ui_source
    assert "Codex · 미연결" in ui_source
    assert "Workbench · 확인 전" in ui_source
    assert ".q-dialog__backdrop" in ui_source
    assert "background: rgba(2, 6, 23, 0.86)" in ui_source
    assert "cae-dialog-card cae-danger" in ui_source
    assert "cae-chat-page" in ui_source
    assert "cae-chat-statusbar" in ui_source
    assert "Codex가 응답을 생성하고 있습니다" in ui_source
    assert "안전 작업 자동 승인" in ui_source
    assert '"activity"' in ui_source
    assert '"maintenance"' in ui_source


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


def test_store_input_upload_creates_only_new_allowed_file(
    tmp_path: Path,
) -> None:
    """허용된 새 입력 파일은 workspace/input 내부에 원문 그대로 저장해야 한다."""
    config = load_config(current_directory=tmp_path)

    stored = store_input_upload(
        config,
        filename="전력모듈.step",
        content=b"STEP DATA",
    )

    assert stored.path == config.workspace.input_dir / "전력모듈.step"
    assert stored.path.read_bytes() == b"STEP DATA"
    assert stored.size_bytes == 9


def test_duplicate_upload_requires_explicit_replacement(
    tmp_path: Path,
) -> None:
    """중복 업로드는 기존 파일을 유지한 채 교체 승인 스냅숏을 반환해야 한다."""
    config = load_config(current_directory=tmp_path)
    first = store_input_upload(
        config,
        filename="package.scdoc",
        content=b"original",
    )

    with pytest.raises(UploadConflict, match="이미 있습니다") as conflict:
        store_input_upload(
            config,
            filename="package.scdoc",
            content=b"replacement",
        )

    assert first.path.read_bytes() == b"original"
    pending = conflict.value.pending
    replaced = replace_input_upload(config, pending)
    assert replaced.path.read_bytes() == b"replacement"
    audit = config.workspace.logs_dir / "upload-replacements.jsonl"
    assert '"event": "input_replaced"' in audit.read_text(encoding="utf-8")


def test_replacement_is_invalidated_when_original_changes(tmp_path: Path) -> None:
    """모달 표시 뒤 기존 파일이 바뀌면 이전 교체 승인을 사용할 수 없어야 한다."""
    config = load_config(current_directory=tmp_path)
    original = store_input_upload(
        config,
        filename="package.step",
        content=b"original",
    )
    with pytest.raises(UploadConflict) as conflict:
        store_input_upload(
            config,
            filename="package.step",
            content=b"replacement",
        )
    original.path.write_bytes(b"changed-after-preview")

    with pytest.raises(UIError, match="기존 파일이 변경"):
        replace_input_upload(config, conflict.value.pending)

    assert original.path.read_bytes() == b"changed-after-preview"


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("../escape.step", "폴더 경로"),
        (r"folder\\escape.step", "폴더 경로"),
        ("solver.exe", "허용되지 않은"),
        ("CON.step", "예약 이름"),
        ("trailing.step.", "끝 공백"),
    ],
)
def test_store_input_upload_rejects_unsafe_names_and_extensions(
    tmp_path: Path,
    filename: str,
    message: str,
) -> None:
    """경로 탈출, 실행 파일과 Windows 특수 파일명은 서버에서 차단해야 한다."""
    config = load_config(current_directory=tmp_path)

    with pytest.raises(UIError, match=message):
        store_input_upload(config, filename=filename, content=b"data")

    assert not config.workspace.input_dir.exists()


def test_store_input_upload_rejects_empty_and_oversized_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """의미 없는 빈 파일과 서버 제한을 넘는 파일은 저장 전에 거부해야 한다."""
    config = load_config(current_directory=tmp_path)
    monkeypatch.setattr("cae_agent.ui.MAX_UPLOAD_SIZE_BYTES", 4)

    with pytest.raises(UIError, match="빈 파일"):
        store_input_upload(config, filename="empty.csv", content=b"")
    with pytest.raises(UIError, match="이하여야"):
        store_input_upload(
            config,
            filename="large.step",
            content=b"12345",
        )

    assert not config.workspace.input_dir.exists()


def test_store_input_upload_rejects_symlinked_input_directory(
    tmp_path: Path,
) -> None:
    """입력 폴더가 외부를 가리키는 링크라면 작업공간 이탈 저장을 차단해야 한다."""
    config = load_config(current_directory=tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    config.workspace.root.mkdir()
    try:
        config.workspace.input_dir.symlink_to(
            external,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("현재 Windows 환경에서 심볼릭 링크를 만들 권한이 없습니다.")

    with pytest.raises(UIError, match="심볼릭 링크"):
        store_input_upload(
            config,
            filename="model.step",
            content=b"data",
        )

    assert not (external / "model.step").exists()
