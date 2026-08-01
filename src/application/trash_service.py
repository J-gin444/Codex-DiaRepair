"""TrashService: 废纸篓管理。事务化恢复 + 验证。"""

import json, os, shutil
from datetime import datetime

class RestoreResult:
    def __init__(self):
        self.ok = False
        self.steps = {}
        self.error = ""

class TrashEntry:
    def __init__(self, id="", title="", provider="", deleted_at="", original_size=0):
        self.id = id; self.title = title; self.provider = provider
        self.deleted_at = deleted_at; self.original_size = original_size

class TrashService:
    def __init__(self, trash_root: str):
        self._root = os.path.abspath(trash_root)
        os.makedirs(self._root, exist_ok=True)

    def move_to_trash(self, thread_ids: list[str], scan_result) -> None:
        now = datetime.now().isoformat()
        for t in scan_result.thread_list:
            if t.id not in thread_ids: continue
            d = os.path.join(self._root, t.id); os.makedirs(d, exist_ok=True)
            meta = {"version":"1.0","thread_id":t.id,"title":t.title,"title_short":t.title_short,
                    "provider":t.provider,"cwd":t.cwd,"source":t.source,"archived":t.archived,
                    "size_bytes":t.size_bytes,"created_at_ms":t.created_at_ms,
                    "updated_at_ms":t.updated_at_ms,"deleted_at":now,"original_rollout_path":t.rollout_path}
            with open(os.path.join(d,"metadata.json"),"w",encoding="utf-8") as f:
                json.dump(meta,f,indent=2,ensure_ascii=False)
            if t.normalized_path and os.path.isfile(t.normalized_path):
                try: shutil.move(t.normalized_path, os.path.join(d,"rollout.jsonl"))
                except OSError: pass

    def list_entries(self) -> list[TrashEntry]:
        entries = []
        for name in os.listdir(self._root):
            d = os.path.join(self._root, name); mp = os.path.join(d,"metadata.json")
            if not os.path.isfile(mp): continue
            try:
                with open(mp,"r",encoding="utf-8") as f: m = json.load(f)
                entries.append(TrashEntry(id=m.get("thread_id",name),
                    title=m.get("title_short",m.get("title","")),
                    provider=m.get("provider",""),deleted_at=m.get("deleted_at",""),
                    original_size=m.get("size_bytes",0)))
            except: pass
        entries.sort(key=lambda e: e.deleted_at, reverse=True)
        return entries

    def restore(self, thread_id: str, codex_path: str = "") -> RestoreResult:
        result = RestoreResult()
        d = os.path.join(self._root, thread_id)
        mp = os.path.join(d, "metadata.json")
        if not os.path.isfile(mp): result.error = "metadata missing"; return result
        try:
            with open(mp,"r",encoding="utf-8") as f: meta = json.load(f)
        except Exception as e:
            import traceback
            result.error = 'sqlite: ' + str(e); return result

        # Step 1: rollout
        src = os.path.join(d, "rollout.jsonl")
        dst = meta.get("original_rollout_path","")
        if src and dst and os.path.isfile(src):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            except Exception as e:
                result.steps["rollout"] = False
                result.error = "rollout: %s" % e
                return result
        else:
            result.steps["rollout"] = "skipped"

        # Step 2: sqlite (use find_state_db, not hardcoded state_5.sqlite)
        if codex_path:
            ok, err = self._reinsert_thread(codex_path, meta)
            result.steps["sqlite_insert"] = ok
            if not ok: result.error = "sqlite: %s"%err; return result
            rv = self._verify_thread(codex_path, thread_id)
            result.steps["sqlite_verify"] = rv
            if not rv: result.error = "sqlite verify failed"; return result

        # Step 3: session_index
        if codex_path:
            ok, err = self._reinsert_session_index(codex_path, meta)
            result.steps["session_index"] = ok
            if not ok: result.error = "session_index: %s"%err; return result

        # Step 4: trash
        try:
            shutil.rmtree(d)
            result.steps["trash_removed"] = True
        except Exception as e:
            import traceback
            result.error = 'sqlite: ' + traceback.format_exc()[-200:]
            result.steps["trash_removed"] = False; result.error = "trash: %s"%e; return result

        result.ok = True
        return result

    def _find_state_db(self, codex_path: str) -> str:
        """复用 Scanner 的 find_state_db 逻辑。"""
        import glob
        pattern = os.path.join(codex_path, "state_*.sqlite")
        matches = [f for f in glob.glob(pattern) if not f.endswith(("-wal","-shm"))]
        if not matches: return os.path.join(codex_path, "state_5.sqlite")
        matches.sort(key=os.path.getmtime, reverse=True)
        return matches[0]

    def _reinsert_thread(self, codex_path: str, meta: dict):
        import sqlite3
        db = self._find_state_db(codex_path)
        if not os.path.isfile(db):
            return False, "db not found: %s" % db
        tid = meta.get("thread_id", "")
        if not tid:
            return False, "empty tid"
        try:
            con = sqlite3.connect(db, timeout=30)
            cols = [r[1] for r in con.execute("PRAGMA table_info(threads)")]
            values = {
                "id": tid,
                "title": meta.get("title", ""),
                "model_provider": meta.get("provider", ""),
                "rollout_path": meta.get("original_rollout_path", ""),
                "created_at_ms": meta.get("created_at_ms", 0),
                "updated_at_ms": meta.get("updated_at_ms", 0),
                "archived": 1 if meta.get("archived") else 0,
                "source": meta.get("source", ""),
                "cwd": meta.get("cwd", ""),
            }
            if "created_at" in cols:
                values["created_at"] = meta.get("created_at_ms", 0)
            if "updated_at" in cols:
                values["updated_at"] = meta.get("updated_at_ms", 0)
            if "sandbox_policy" in cols and "approval_mode" in cols:
                def_row = con.execute(
                    "SELECT sandbox_policy, approval_mode FROM threads LIMIT 1").fetchone()
                values["sandbox_policy"] = def_row[0] if def_row else ""
                values["approval_mode"] = def_row[1] if def_row else ""
            present = [c for c in values if c in cols]
            ph = ",".join("?" for _ in present)
            con.execute(
                "INSERT OR REPLACE INTO threads (%s) VALUES (%s)" % (", ".join(present), ph),
                [values[c] for c in present],
            )
            con.commit()
            con.close()
            return True, ""
        except Exception as e:
            return False, str(e)

    def _verify_thread(self, codex_path: str, thread_id: str) -> bool:
        import sqlite3
        db = self._find_state_db(codex_path)
        if not os.path.isfile(db): return False
        try:
            con = sqlite3.connect(db, timeout=5)
            row = con.execute("SELECT 1 FROM threads WHERE id=?",(thread_id,)).fetchone()
            con.close()
            return row is not None
        except: return False

    def _reinsert_session_index(self, codex_path: str, meta: dict):
        import json as _json
        idx = os.path.join(codex_path, "session_index.jsonl")
        tid = meta.get("thread_id","")
        if not tid: return False, "empty id"
        entry = _json.dumps({"id":tid, "thread_name": meta.get("title_short", meta.get("title","")),
                             "updated_at": meta.get("deleted_at", datetime.now().isoformat())},
                            ensure_ascii=False) + "\n"
        try:
            with open(idx, "a", encoding="utf-8") as f: f.write(entry)
            return True, ""
        except Exception as e:
            import traceback
            return False, str(e)

    def empty_trash(self):
        for name in os.listdir(self._root):
            d = os.path.join(self._root, name)
            if os.path.isdir(d):
                try: shutil.rmtree(d)
                except: pass

    def delete_single_from_trash(self, tid):
        d = os.path.join(self._root, tid)
        if os.path.isdir(d):
            try: shutil.rmtree(d)
            except: pass
