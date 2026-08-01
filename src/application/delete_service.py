"""DeleteService: 彻底删除。不可逆，需 backup。"""

import os, json
from ..scanner.models import ScanResult
from ..repair.models import RepairStatus, RepairExecutionResult

class DeleteResult:
    def __init__(self, ok=0, failed=0, backup_path=""):
        self.ok = ok; self.failed = failed; self.backup_path = backup_path

class DeleteService:
    def __init__(self, codex_path: str, backup_root: str):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))
        self._backup_root = backup_root

    def permanent_delete(self, thread_ids: list[str]) -> DeleteResult:
        if not thread_ids: return DeleteResult()
        from ..repair import BackupManager, RepairContext, execute, RepairAction, RepairPlan
        from ..diagnosis.models import IssueType

        ctx = RepairContext(codex_path=self._codex_path, backup_scope=[
            os.path.join(self._codex_path, f)
            for f in ["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl", "config.toml"]
        ])
        mgr = BackupManager(backup_root=self._backup_root)
        snap = mgr.create_backup(ctx)
        if not snap.verified:
            return DeleteResult(failed=len(thread_ids), backup_path="")

        action = RepairAction(
            issue_type=IssueType.MISSING_SESSION_FILE, action_type="delete_thread",
            target_files=["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl"],
            thread_id=",".join(thread_ids), risk_level="high", requires_confirmation=False,
            description="Permanently delete %d threads" % len(thread_ids),
        )
        result = execute(RepairPlan(actions=[action], total=1, auto_count=1), snap)
        return DeleteResult(ok=result.success_count, failed=result.failed_count, backup_path=snap.path)
