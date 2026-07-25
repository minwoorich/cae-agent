"""SpaceClaim 실행기의 파일 보존, 저널 생성 및 결과 검증을 시험한다."""

import json
from pathlib import Path

import pytest

from cae_agent.config import load_config
from cae_agent.spaceclaim import (
    SpaceClaimError,
    build_workbench_journal,
    run_spaceclaim_script,
    stage_script,
)


def test_script_is_staged_without_changing_original(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "geometry.py"
    source.write_text("# Python Script, API Version = V261\n", encoding="utf-8")

    staged = stage_script(config, source, run_id="abc123")

    assert staged == config.workspace.generated_dir / "spaceclaim_abc123.py"
    assert staged.read_bytes() == source.read_bytes()
    assert source.is_file()


def test_non_python_script_is_rejected(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "geometry.txt"
    source.write_text("content", encoding="utf-8")

    with pytest.raises(SpaceClaimError, match=".py"):
        stage_script(config, source, run_id="abc123")


def test_journal_targets_requested_system_and_optional_clear() -> None:
    journal = build_workbench_journal(
        system_name="SYS 1",
        uploaded_script_name="spaceclaim_abc.py",
        result_file_name="spaceclaim_abc.result.txt",
        clear_geometry=True,
    )

    assert "GetSystem(Name='SYS 1')" in journal
    assert 'Command="ClearAll()"' in journal
    assert "'spaceclaim_abc.py'" in journal
    assert "traceback.format_exc()" in journal
    assert "Save(Overwrite=True)" in journal
    assert "finally:" in journal
    # 생성된 저널이 최소한 유효한 Python 문법인지 외부 실행 없이 확인한다.
    compile(journal, "<workbench-journal>", "exec")


def test_runner_uploads_and_returns_validated_result(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "geometry.py"
    source.write_text("print('SpaceClaim only')", encoding="utf-8")

    class FakeWorkbench:
        uploaded: tuple[str, bool] | None = None
        journal: str | None = None

        def upload_file(self, path: str, *, show_progress: bool) -> None:
            self.uploaded = (path, show_progress)

        def run_script_string(self, journal: str) -> str:
            self.journal = journal
            return json.dumps(
                {
                    "status": "success",
                    "system_name": "SYS",
                    "message": "SUCCESS",
                }
            )

    workbench = FakeWorkbench()
    result = run_spaceclaim_script(
        config,
        source,
        system_name="SYS",
        run_id_factory=lambda: "fixed",
        workbench=workbench,
    )

    assert result.run_id == "fixed"
    assert result.status == "success"
    assert workbench.uploaded is not None
    assert workbench.uploaded[0].endswith("spaceclaim_fixed.py")
    assert workbench.uploaded[1] is False
    assert workbench.journal is not None


def test_invalid_workbench_result_is_rejected(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "geometry.py"
    source.write_text("pass", encoding="utf-8")

    class FakeWorkbench:
        def upload_file(self, _path: str, *, show_progress: bool) -> None:
            pass

        def run_script_string(self, _journal: str) -> str:
            return "not-json"

    with pytest.raises(SpaceClaimError, match="잘못된"):
        run_spaceclaim_script(
            config,
            source,
            system_name="SYS",
            run_id_factory=lambda: "fixed",
            workbench=FakeWorkbench(),
        )


def test_system_name_mismatch_is_rejected(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)
    source = tmp_path / "geometry.py"
    source.write_text("pass", encoding="utf-8")

    class FakeWorkbench:
        def upload_file(self, _path: str, *, show_progress: bool) -> None:
            pass

        def run_script_string(self, _journal: str) -> str:
            return json.dumps(
                {
                    "status": "success",
                    "system_name": "OTHER",
                    "message": "SUCCESS",
                }
            )

    with pytest.raises(SpaceClaimError, match="다릅니다"):
        run_spaceclaim_script(
            config,
            source,
            system_name="SYS",
            run_id_factory=lambda: "fixed",
            workbench=FakeWorkbench(),
        )
