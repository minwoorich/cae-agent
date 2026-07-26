"""로컬 NiceGUI 대시보드의 안정적인 공개 진입점을 제공한다."""

from cae_agent.ui.dashboard import (
    ServiceConnection,
    build_dashboard,
    launch_ui,
    probe_workbench_connection,
)
from cae_agent.ui.files import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_SIZE_BYTES,
    DashboardSnapshot,
    InputFileSummary,
    PendingUploadReplacement,
    StoredUpload,
    UIError,
    UploadConflict,
    dashboard_snapshot,
    input_file_summaries,
    replace_input_upload,
    store_input_upload,
)

__all__ = [
    "ALLOWED_UPLOAD_EXTENSIONS",
    "MAX_UPLOAD_SIZE_BYTES",
    "DashboardSnapshot",
    "InputFileSummary",
    "PendingUploadReplacement",
    "ServiceConnection",
    "StoredUpload",
    "UIError",
    "UploadConflict",
    "build_dashboard",
    "dashboard_snapshot",
    "input_file_summaries",
    "launch_ui",
    "probe_workbench_connection",
    "replace_input_upload",
    "store_input_upload",
]
