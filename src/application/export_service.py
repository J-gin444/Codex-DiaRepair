"""ExportService: 导出对话记录为 JSON。"""

import json, os
from ..scanner.models import ScanResult

class ExportResult:
    def __init__(self, exported=0, failed=0, files=None):
        self.exported = exported; self.failed = failed; self.files = files or []

class ExportService:
    @staticmethod
    def export_threads(thread_ids: list[str], scan_result: ScanResult, output_dir: str) -> ExportResult:
        exported = []; failed = []
        os.makedirs(output_dir, exist_ok=True)
        for t in scan_result.thread_list:
            if t.id not in thread_ids: continue
            try:
                data = {
                    "thread_id": t.id, "title": t.title, "provider": t.provider,
                    "created_at_ms": t.created_at_ms, "updated_at_ms": t.updated_at_ms,
                    "rollout_path": t.rollout_path, "rollout_content": "",
                    "source": t.source, "cwd": t.cwd, "archived": t.archived,
                }
                if t.normalized_path and os.path.isfile(t.normalized_path):
                    try:
                        with open(t.normalized_path, "r", encoding="utf-8-sig", errors="replace") as f:
                            data["rollout_content"] = f.read()
                    except Exception: pass
                out_path = os.path.join(output_dir, "%s.json" % t.id)
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                exported.append(out_path)
            except Exception:
                failed.append(t.id)
        return ExportResult(exported=len(exported), failed=len(failed), files=exported)
