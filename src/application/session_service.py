"""SessionService: 对话会话管理。扫描、同步、筛选。"""

import os
from datetime import datetime
from ..scanner import scan_codex_home
from ..scanner.models import ScanResult, ThreadInfo
from .options import RepairOptions


class SyncResult:
    def __init__(self, added=0, removed=0, updated=0):
        self.added = added
        self.removed = removed
        self.updated = updated
        self.timestamp = datetime.now().isoformat()


class SessionService:
    def __init__(self, codex_path: str):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))
        self._last_ids: set[str] = set()

    def scan(self) -> ScanResult:
        result = scan_codex_home(self._codex_path)
        self._last_ids = {t.id for t in result.thread_list}
        return result

    def sync(self) -> SyncResult:
        current = scan_codex_home(self._codex_path)
        current_ids = {t.id for t in current.thread_list}
        added = current_ids - self._last_ids
        removed = self._last_ids - current_ids
        updated = len(current_ids & self._last_ids)
        self._last_ids = current_ids
        return SyncResult(added=len(added), removed=len(removed), updated=updated)
