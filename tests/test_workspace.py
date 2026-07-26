"""작업공간 상태 조회와 보존 기간 기반 안전 정리를 검증한다."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cae_agent.config import load_config, prepare_workspace
from cae_agent.workspace import (
    WorkspaceError,
    clean_workspace,
    cleanup_candidates,
    workspace_status,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path):
    """각 테스트가 외부 파일에 접근하지 않는 격리 설정을 반환한다."""
    config = load_config(current_directory=tmp_path)
    prepare_workspace(config.workspace)
    return config


def _write_with_age(path: Path, content: str, *, days_old: int) -> None:
    """테스트 파일을 만들고 수정 시간을 기준 시각 이전으로 조정한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    modified = (NOW - timedelta(days=days_old)).timestamp()
    os.utime(path, (modified, modified))


def test_workspace_status_reports_each_directory_and_total(tmp_path: Path) -> None:
    """빈 폴더와 파일이 있는 폴더를 모두 포함해 합계를 계산해야 한다."""
    config = _config(tmp_path)
    (config.workspace.input_dir / "request.txt").write_text(
        "1234",
        encoding="utf-8",
    )
    (config.workspace.results_dir / "model.wbpj").write_text(
        "123456",
        encoding="utf-8",
    )

    status = workspace_status(config)
    usages = {item.name: item for item in status.directories}

    assert set(usages) == {"input", "generated", "logs", "results", "runtime"}
    assert usages["input"].size_bytes == 4
    assert usages["results"].size_bytes == 6
    assert status.total_file_count == 2
    assert status.total_size_bytes == 10


def test_cleanup_dry_run_never_changes_files(tmp_path: Path) -> None:
    """승인 없는 기본 실행은 오래된 후보를 찾아도 삭제하지 않아야 한다."""
    config = _config(tmp_path)
    old_script = config.workspace.generated_dir / "old.py"
    _write_with_age(old_script, "old", days_old=31)

    result = clean_workspace(config, older_than_days=30, now=NOW)

    assert result.dry_run is True
    assert result.approved is False
    assert len(result.candidates) == 1
    assert old_script.is_file()
    assert result.deleted == ()
    assert result.audit_log is None


def test_approved_cleanup_deletes_only_old_safe_files(tmp_path: Path) -> None:
    """오래된 생성본·로그만 지우고 새 파일, 원본과 결과는 보존해야 한다."""
    config = _config(tmp_path)
    old_generated = config.workspace.generated_dir / "old.py"
    new_generated = config.workspace.generated_dir / "new.py"
    old_log = config.workspace.logs_dir / "old.log"
    input_file = config.workspace.input_dir / "source.py"
    result_file = config.workspace.results_dir / "model.wbpj"
    _write_with_age(old_generated, "old generated", days_old=31)
    _write_with_age(new_generated, "new generated", days_old=1)
    _write_with_age(old_log, "old log", days_old=31)
    _write_with_age(input_file, "input", days_old=365)
    _write_with_age(result_file, "result", days_old=365)

    result = clean_workspace(
        config,
        older_than_days=30,
        approve=True,
        now=NOW,
    )

    assert not old_generated.exists()
    assert not old_log.exists()
    assert new_generated.is_file()
    assert input_file.is_file()
    assert result_file.is_file()
    assert len(result.deleted) == 2
    assert result.failures == ()
    assert result.audit_log is not None
    audit = Path(result.audit_log)
    assert audit.is_file()
    assert json.loads(audit.read_text(encoding="utf-8"))["approved"] is True


@pytest.mark.parametrize("session_kind", ["workbench", "mechanical"])
def test_active_session_metadata_blocks_approved_cleanup(
    tmp_path: Path,
    session_kind: str,
) -> None:
    """세션이 실행 중일 가능성이 있으면 실제 정리를 보수적으로 차단한다."""
    config = _config(tmp_path)
    old_script = config.workspace.generated_dir / "old.py"
    _write_with_age(old_script, "old", days_old=31)
    if session_kind == "workbench":
        session_file = (
            config.workspace.root
            / ".runtime"
            / "workbench"
            / "session.json"
        )
    else:
        session_file = (
            config.workspace.root
            / ".runtime"
            / "mechanical"
            / "system.json"
        )
    session_file.parent.mkdir(parents=True)
    session_file.write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="세션 파일"):
        clean_workspace(
            config,
            older_than_days=30,
            approve=True,
            now=NOW,
        )

    assert old_script.is_file()


def test_cleanup_rejects_negative_retention(tmp_path: Path) -> None:
    """음수 보존 기간으로 모든 파일이 선택되는 실수를 거부해야 한다."""
    config = _config(tmp_path)

    with pytest.raises(WorkspaceError, match="0일 이상"):
        cleanup_candidates(config, older_than_days=-1, now=NOW)


def test_symlink_is_skipped_without_following_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """링크로 판정된 파일은 후보에 포함하거나 외부 대상을 따라가면 안 된다."""
    config = _config(tmp_path)
    linked = config.workspace.generated_dir / "linked.py"
    _write_with_age(linked, "do not delete", days_old=31)
    original = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return path == linked or original(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    candidates, skipped = cleanup_candidates(
        config,
        older_than_days=30,
        now=NOW,
    )

    assert candidates == ()
    assert str(linked) in skipped
    assert linked.is_file()


def test_codex_runtime_is_cleaned_but_other_runtime_is_preserved(
    tmp_path: Path,
) -> None:
    """Codex 임시 파일만 지우고 Workbench 통신 폴더는 자동 정리하지 않는다."""
    config = _config(tmp_path)
    codex_file = (
        config.workspace.root / ".runtime" / "codex" / "run" / "response.json"
    )
    workbench_file = (
        config.workspace.root
        / ".runtime"
        / "workbench"
        / "server"
        / "exchange.txt"
    )
    _write_with_age(codex_file, "temporary", days_old=31)
    _write_with_age(workbench_file, "keep", days_old=31)

    result = clean_workspace(
        config,
        older_than_days=30,
        approve=True,
        now=NOW,
    )

    assert not codex_file.exists()
    assert workbench_file.is_file()
    assert str(codex_file) in result.deleted


def test_cleanup_reports_partial_failure_and_keeps_audit_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """파일 하나의 삭제 실패를 숨기지 않고 성공 내역과 함께 기록해야 한다."""
    config = _config(tmp_path)
    removable = config.workspace.generated_dir / "removable.py"
    blocked = config.workspace.generated_dir / "blocked.py"
    _write_with_age(removable, "remove", days_old=31)
    _write_with_age(blocked, "keep after failure", days_old=31)
    original_unlink = Path.unlink

    def selective_unlink(path: Path, *args, **kwargs) -> None:
        if path == blocked:
            raise PermissionError("테스트용 접근 거부")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", selective_unlink)
    result = clean_workspace(
        config,
        older_than_days=30,
        approve=True,
        now=NOW,
    )

    assert not removable.exists()
    assert blocked.exists()
    assert str(removable) in result.deleted
    assert len(result.failures) == 1
    assert "테스트용 접근 거부" in result.failures[0]
    assert result.audit_log is not None
    assert Path(result.audit_log).is_file()
