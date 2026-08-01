import os
from ..scanner import scan_codex_home
from ..diagnosis import diagnose
from ..repair import plan, BackupManager, execute, RepairContext, RepairStatus
from ..diagnosis.models import DiagnosisResult
from ..repair.models import RepairPlan, RepairExecutionResult
from .backup_service import core_backup_scope
from .options import RepairOptions, default_backup_root


class RepairService:
    def __init__(self, codex_path: str, options: RepairOptions | None = None):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))
        self._scan_result = None
        self._options = options or RepairOptions()

    def scan(self):
        self._scan_result = scan_codex_home(self._codex_path)
        return self._scan_result

    def diagnose(self) -> DiagnosisResult:
        if self._scan_result is None: self.scan()
        return diagnose(self._scan_result)

    def plan(self, diagnosis: DiagnosisResult | None = None) -> RepairPlan:
        if diagnosis is None: diagnosis = self.diagnose()
        return plan(diagnosis, self._make_context())

    def execute(self, plan: RepairPlan) -> RepairExecutionResult:
        mgr = self._make_backup_manager()
        snap = mgr.create_backup(self._make_context())
        if not snap.verified:
            return RepairExecutionResult(status=RepairStatus.FAILED, summary="Backup failed.")
        return execute(plan, snap)

    def delete_threads(self, thread_ids: list[str]) -> RepairExecutionResult | None:
        if not thread_ids: return None
        from ..repair.models import RepairAction
        from ..diagnosis.models import IssueType
        action = RepairAction(
            issue_type=IssueType.MISSING_SESSION_FILE, action_type="delete_thread",
            target_files=["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl"],
            thread_id=",".join(thread_ids), risk_level="high", requires_confirmation=False,
            description="Delete %d threads" % len(thread_ids),
        )
        mgr = self._make_backup_manager()
        snap = mgr.create_backup(self._make_context())
        if not snap.verified:
            return RepairExecutionResult(status=RepairStatus.FAILED, summary="Backup failed.")
        return execute(RepairPlan(actions=[action], total=1, auto_count=1), snap)

    def _make_context(self) -> RepairContext:
        return RepairContext(codex_path=self._codex_path, backup_scope=core_backup_scope(self._codex_path))

    def _make_backup_manager(self) -> BackupManager:
        d = self._options.backup.directory or default_backup_root()
        return BackupManager(backup_root=d)
