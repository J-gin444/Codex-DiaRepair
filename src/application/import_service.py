"""ImportService: 从 JSON 导入对话记录。"""

import json, os, sqlite3, glob
from datetime import datetime

class ImportResult:
    def __init__(self, imported=0, skipped=0, failed=0, status=""):
        self.imported = imported; self.skipped = skipped; self.failed = failed; self.status = status or ""

class ImportService:
    def __init__(self, codex_path: str):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))

    def import_threads(self, import_dir: str, overwrite: bool = False) -> ImportResult:
        files = sorted(glob.glob(os.path.join(import_dir, "*.json")))
        if not files:
            return ImportResult(status="no .json files found")

        db_path = self._find_db()
        if not os.path.isfile(db_path):
            return ImportResult(status="state database not found")

        existing_ids = self._get_existing_ids(db_path)
        imported = skipped = failed = 0
        new_threads = []

        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                failed += 1; continue

            tid = data.get("thread_id", "")
            if not tid:
                failed += 1; continue

            if tid in existing_ids and not overwrite:
                skipped += 1; continue

            title = data.get("title", "") or ""
            provider = data.get("provider", "") or ""
            rollout_content = data.get("rollout_content", "") or ""

            # 恢复到 Codex sessions 目录结构 (sessions/imported/)
            rollout_dir = os.path.join(self._codex_path, "sessions", "imported")
            os.makedirs(rollout_dir, exist_ok=True)
            rollout_path = os.path.join(rollout_dir, "%s.jsonl" % tid)
            if rollout_content:
                try:
                    with open(rollout_path, "w", encoding="utf-8") as f:
                        f.write(rollout_content)
                except Exception:
                    rollout_path = ""

            new_threads.append((
                tid, title, provider, rollout_path,
                data.get("created_at_ms", 0), data.get("created_at_ms", 0),  # created_at 复用 ms 值
                data.get("updated_at_ms", 0), data.get("updated_at_ms", 0),  # updated_at 复用 ms 值
            ))
            imported += 1

        if new_threads:
            self._write_to_db(db_path, new_threads)
            self._sync_session_index(new_threads)

        return ImportResult(imported=imported, skipped=skipped, failed=failed,
                            status="imported=%d skipped=%d failed=%d" % (imported, skipped, failed))

    def _find_db(self) -> str:
        pattern = os.path.join(self._codex_path, "state_*.sqlite")
        matches = [f for f in glob.glob(pattern) if not f.endswith(("-wal","-shm"))]
        if not matches:
            return os.path.join(self._codex_path, "state_5.sqlite")
        matches.sort(key=os.path.getmtime, reverse=True)
        return matches[0]

    def _get_existing_ids(self, db_path: str) -> set[str]:
        try:
            con = sqlite3.connect(db_path, timeout=5)
            ids = {r[0] for r in con.execute("SELECT id FROM threads").fetchall()}
            con.close()
            return ids
        except Exception:
            return set()

    def _write_to_db(self, db_path: str, threads: list[tuple]) -> None:
        con = sqlite3.connect(db_path, timeout=30)
        try:
            # 从现有 thread 取 NOT NULL 默认值
            def_row = con.execute(
                "SELECT sandbox_policy, approval_mode, source, cwd FROM threads LIMIT 1"
            ).fetchone()
            sp = def_row[0] if def_row else ""
            am = def_row[1] if def_row else ""
            src = def_row[2] if def_row else "vscode"
            cwd = def_row[3] if def_row else ""

            con.executemany(
                """INSERT OR REPLACE INTO threads
                   (id, title, model_provider, rollout_path,
                    created_at, created_at_ms, updated_at, updated_at_ms, archived,
                    source, cwd, sandbox_policy, approval_mode)
                   VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?)""",
                [(t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7],
                  src, cwd, sp, am) for t in threads]
            )
            con.commit()
            con.close()
        except Exception as e:
            con.close()
            raise

    def _sync_session_index(self, threads: list[tuple]) -> None:
        idx_path = os.path.join(self._codex_path, "session_index.jsonl")
        now = datetime.now().isoformat()
        try:
            with open(idx_path, "a", encoding="utf-8") as f:
                for t in threads:
                    entry = json.dumps({
                        "id": t[0], "thread_name": t[1],
                        "updated_at": now,
                    }, ensure_ascii=False)
                    f.write(entry + "\n")
        except Exception:
            pass
