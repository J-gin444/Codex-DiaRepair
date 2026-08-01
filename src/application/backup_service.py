"""BackupService: 备份导出、导入校验、恢复。独立于 Repair。"""

import json, os, shutil
from datetime import datetime
from ..repair import BackupManager, BackupSnapshot, BackupFile, RepairContext


class BackupInfo:
    def __init__(self, path="", created_at="", source="", threads=0, files=0, size=0,
                 verified=False, has_sessions=False, session_count=0):
        self.path = path
        self.created_at = created_at
        self.source = source
        self.threads = threads
        self.files = files
        self.size = size
        self.verified = verified
        self.has_sessions = has_sessions
        self.session_count = session_count


class RestoreResult:
    def __init__(self, success=False, before=0, after=0, restored_files=None):
        self.success = success
        self.before = before
        self.after = after
        self.restored_files = restored_files or []


class BackupService:
    def __init__(self, codex_path: str, backup_root: str):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))
        self._backup_root = os.path.abspath(backup_root)
        os.makedirs(self._backup_root, exist_ok=True)

    def create_backup(self) -> BackupInfo:
        """导出当前 Codex 数据为完整备份。"""
        ctx = RepairContext(codex_path=self._codex_path, backup_scope=full_backup_scope(self._codex_path))
        mgr = BackupManager(backup_root=self._backup_root)
        snap = mgr.create_backup(ctx)

        threads = 0
        try:
            import sqlite3
            db = os.path.join(self._codex_path, "state_5.sqlite")
            if os.path.isfile(db):
                con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
                threads = con.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
                con.close()
        except Exception:
            pass

        total_size = sum(bf.size for bf in snap.files)
        return BackupInfo(
            path=snap.path, created_at=snap.created_at, source=snap.source,
            threads=threads, files=len(snap.files), size=total_size,
            verified=snap.verified,
            has_sessions=any(
                bf.backup_path.startswith(("sessions", "archived_sessions"))
                for bf in snap.files
            ),
            session_count=sum(
                1 for bf in snap.files
                if bf.backup_path.startswith(("sessions", "archived_sessions"))
            ),
        )

    def list_backups(self) -> list[BackupInfo]:
        """列出所有历史备份。"""
        results = []
        for name in sorted(os.listdir(self._backup_root), reverse=True):
            d = os.path.join(self._backup_root, name)
            if not os.path.isdir(d): continue
            if name == "trash": continue
            manifest_path = os.path.join(d, "manifest.json")
            if not os.path.isfile(manifest_path): continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                files = m.get("files", [])
                size = sum(f.get("size", 0) for f in files)
                ver = _verify_manifest(d, m)
                results.append(BackupInfo(
                    path=d, created_at=m.get("created_at", ""), source=m.get("source", ""),
                    threads=0, files=len(files), size=size, verified=ver,
                    has_sessions=_manifest_has_sessions(files),
                    session_count=_manifest_session_count(files),
                ))
            except Exception:
                pass
        return results

    def validate_backup(self, backup_path: str) -> BackupInfo | None:
        """校验外部备份目录的完整性。"""
        manifest_path = os.path.join(backup_path, "manifest.json")
        if not os.path.isfile(manifest_path): return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                m = json.load(f)
        except Exception:
            return None
        files = m.get("files", [])
        size = sum(f.get("size", 0) for f in files)
        ver = _verify_manifest(backup_path, m)
        return BackupInfo(
            path=backup_path, created_at=m.get("created_at", ""), source=m.get("source", ""),
            threads=0, files=len(files), size=size, verified=ver,
            has_sessions=_manifest_has_sessions(files),
            session_count=_manifest_session_count(files),
        )

    def restore_full(self, backup_path: str) -> RestoreResult:
        """完整恢复：将备份目录下的所有文件覆盖到 .codex。"""
        manifest_path = os.path.join(backup_path, "manifest.json")
        if not os.path.isfile(manifest_path): return RestoreResult()
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)

        before_count = 0
        try:
            import sqlite3
            db = os.path.join(self._codex_path, "state_5.sqlite")
            if os.path.isfile(db):
                con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
                before_count = con.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
                con.close()
        except Exception:
            pass

        restored = []
        for entry in m.get("files", []):
            src = os.path.join(backup_path, entry["backup_path"])
            dst = entry.get("original_path", os.path.join(self._codex_path, entry["backup_path"]))
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                restored.append(os.path.basename(dst))

        after_count = 0
        try:
            import sqlite3
            db = os.path.join(self._codex_path, "state_5.sqlite")
            if os.path.isfile(db):
                con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
                after_count = con.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
                con.close()
        except Exception:
            pass

        return RestoreResult(success=len(restored) > 0, before=before_count, after=after_count, restored_files=restored)

    def get_backup_threads(self, backup_path: str) -> list[dict]:
        """预览备份中包含的对话项（仅完整备份，核心备份返回空列表）。"""
        if not os.path.isdir(backup_path):
            return []
        manifest_path = os.path.join(backup_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            return []
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        files = manifest.get("files", [])
        if not any(
            f.get("backup_path", "").startswith(("sessions", "archived_sessions"))
            for f in files
        ):
            return []  # 仅核心数据的备份没有会话文件，不存在对话项

        state_db = os.path.join(backup_path, "state_5.sqlite")
        if os.path.isfile(state_db):
            try:
                import sqlite3
                con = sqlite3.connect("file:%s?mode=ro" % state_db, uri=True, timeout=5)
                cols = [r[1] for r in con.execute("PRAGMA table_info(threads)")]
                sel = [c for c in ("id", "title", "model_provider", "updated_at_ms") if c in cols]
                rows = con.execute("SELECT %s FROM threads ORDER BY updated_at_ms DESC" % ", ".join(sel)).fetchall()
                con.close()
                return [dict(zip(sel, r)) for r in rows]
            except Exception:
                pass
        # 没有 state 数据库时，从备份中的会话文件首行提取
        out = []
        for root in ("sessions", "archived_sessions"):
            base = os.path.join(backup_path, root)
            if not os.path.isdir(base):
                continue
            for dirpath, _dirnames, filenames in os.walk(base):
                for fn in filenames:
                    if not fn.endswith(".jsonl"):
                        continue
                    p = os.path.join(dirpath, fn)
                    try:
                        with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                            first = json.loads(f.readline())
                        pl = first.get("payload", {})
                        out.append({
                            "id": pl.get("id") or fn,
                            "title": "",
                            "model_provider": pl.get("model_provider", ""),
                            "updated_at_ms": 0,
                        })
                    except Exception:
                        out.append({"id": fn, "title": "", "model_provider": "", "updated_at_ms": 0})
        return out

    def get_backup_files(self, backup_path: str) -> list[dict]:
        """列出备份中包含的文件（备份路径 + 大小），用于核心备份预览。"""
        manifest_path = os.path.join(backup_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            return []
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return [
            {"path": f.get("backup_path", ""), "size": f.get("size", 0)}
            for f in manifest.get("files", [])
        ]

    def delete_backup(self, backup_path: str) -> tuple[bool, str]:
        """删除一个备份目录。只允许删除备份根目录下的子目录。"""
        target = os.path.abspath(backup_path)
        root = os.path.abspath(self._backup_root)
        if not target.startswith(root + os.sep) or target == root:
            return False, "目标不在备份根目录内"
        if os.path.basename(target) == "trash":
            return False, "不能删除废纸篓目录"
        if not os.path.isdir(target):
            return False, "备份目录不存在"
        try:
            shutil.rmtree(target)
            return True, ""
        except OSError as e:
            return False, str(e)

def _verify_manifest(backup_path, manifest):
    mgr = BackupManager()
    return mgr.verify_backup(backup_path, manifest)


def full_backup_scope(codex_path: str) -> list[str]:
    """完整备份范围：核心文件 + 全部 session 会话文件。"""
    scope = [
        os.path.join(codex_path, f)
        for f in ["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl", "config.toml"]
    ]
    for sub in ("sessions", "archived_sessions"):
        root = os.path.join(codex_path, sub)
        if os.path.isdir(root):
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    if fn.endswith(".jsonl"):
                        scope.append(os.path.join(dirpath, fn))
    return scope


def core_backup_scope(codex_path: str) -> list[str]:
    """修复流程的备份范围：只含核心数据（数据库/索引/配置），不含会话文件。"""
    return [
        os.path.join(codex_path, f)
        for f in ["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl", "config.toml"]
    ]


def _manifest_has_sessions(files) -> bool:
    return any(
        f.get("backup_path", "").startswith(("sessions", "archived_sessions"))
        for f in files
    )


def _manifest_session_count(files) -> int:
    return sum(
        1 for f in files
        if f.get("backup_path", "").startswith(("sessions", "archived_sessions"))
    )
