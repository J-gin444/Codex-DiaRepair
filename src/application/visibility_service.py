"""VisibilityService: 对话可见度诊断与修复编排。

面向用户目标的 Orchestrator，不是新的底层修复器：
- 自动交叉比对数据库 / session 文件 / 索引 / 废纸篓 / 备份 五个来源；
- 只生成诊断与修复建议，不自动执行；
- 用户确认后先完整备份，再按"先恢复真实 session，再修 DB/index"的顺序执行；
- 绝不修改认证配置与 provider 配置（与 DeepSeek API 登录方式完全解耦）。
"""

import json
import os
import re
import sqlite3
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime

from ..scanner.sqlite_reader import find_state_db
from ..scanner.config_reader import read_config
from .backup_service import BackupService
from .options import default_backup_root
from .trash_service import TrashService

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

# 执行优先级：先恢复真实会话内容，再修 DB / 索引
EXECUTION_ORDER = {
    "provider_mismatch": 0,
    "in_trash": 0,
    "missing_session": 1,
    "in_backup_only": 2,
    "missing_db_row": 3,
    "missing_index": 4,
    "index_orphan": 5,
    "invalid_path": 6,
    "whole_db_restore": 99,
}


@dataclass
class VisibilityFinding:
    thread_id: str = ""
    kind: str = ""          # missing_session | missing_db_row | missing_index | index_orphan | invalid_path | in_trash | in_backup_only | whole_db_restore
    risk: str = ""          # low | medium | high
    summary: str = ""
    detail: str = ""
    suggestion: str = ""
    source: str = ""        # trash | backup | session | db | index
    payload: dict = field(default_factory=dict)


@dataclass
class VisibilityReport:
    codex_path: str = ""
    findings: list = field(default_factory=list)
    summary: str = ""
    has_high_risk: bool = False


class VisibilityService:
    """对话可见度诊断与一键编排修复。"""

    def __init__(self, codex_path: str, backup_root: str = ""):
        self._codex_path = os.path.abspath(os.path.expanduser(codex_path))
        self._backup_root = backup_root or default_backup_root()
        self._backup_svc = BackupService(self._codex_path, self._backup_root)
        self._trash = TrashService(os.path.join(self._backup_root, "trash"))

    # ---------------- 前置检查 ----------------

    def is_codex_running(self) -> bool:
        """检测 Codex / ChatGPT 桌面应用是否在运行。

        运行期间修改 state_5.sqlite 会被应用覆盖，必须禁止执行。
        """
        try:
            out = subprocess.run(
                ["tasklist"], capture_output=True, text=True, timeout=15
            ).stdout.lower()
        except Exception:
            return False
        names = {line.strip().split()[0] for line in out.splitlines() if line.strip()}
        for name in names:
            if name in ("codex.exe", "chatgpt.exe"):
                return True
            if name.startswith("codex-command-runner"):
                return True
        return False

    # ---------------- 数据采集 ----------------

    def _read_db(self) -> tuple[dict, str]:
        """读取 threads 表：{id: row_dict}，仅取存在的列。"""
        db_path = find_state_db(self._codex_path)
        rows: dict = {}
        if not db_path or not os.path.isfile(db_path):
            return rows, ""
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=30)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(threads)")]
            common = [c for c in (
                "id", "rollout_path", "title", "model_provider", "archived",
                "updated_at_ms", "created_at_ms", "source", "cwd", "tokens_used",
            ) if c in cols]
            for row in con.execute("SELECT %s FROM threads" % ", ".join(common)):
                rows[row[0]] = dict(zip(common, row))
        finally:
            con.close()
        return rows, db_path

    def _scan_session_files(self) -> dict:
        """扫描 sessions/ 与 archived_sessions/：{thread_id: path}。"""
        out = {}
        for sub in ("sessions", "archived_sessions"):
            root = os.path.join(self._codex_path, sub)
            if not os.path.isdir(root):
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    if not fn.endswith(".jsonl"):
                        continue
                    m = UUID_RE.search(fn)
                    if m:
                        out.setdefault(m.group(0).lower(), os.path.join(dirpath, fn))
        return out

    def _read_index(self) -> dict:
        """读取 session_index.jsonl：{id: {thread_name, updated_at}}。"""
        idx_path = os.path.join(self._codex_path, "session_index.jsonl")
        out = {}
        if not os.path.isfile(idx_path):
            return out
        with open(idx_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(o, dict) and o.get("id"):
                    out[o["id"].lower()] = o
        return out

    def _load_backups(self) -> list[dict]:
        """读取备份快照：含会话文件的原始路径与是否存在 state 数据库。"""
        snapshots = []
        for info in self._backup_svc.list_backups():
            manifest_path = os.path.join(info.path, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            sessions = {}
            has_state_db = False
            for entry in manifest.get("files", []):
                orig = entry.get("original_path", "")
                rel = entry.get("backup_path", "")
                base = os.path.basename(orig)
                if base.startswith("state_") and base.endswith(".sqlite"):
                    has_state_db = True
                if "/sessions/" in orig.replace("\\", "/") or "/archived_sessions/" in orig.replace("\\", "/"):
                    m = UUID_RE.search(orig)
                    if m:
                        sessions.setdefault(m.group(0).lower(), []).append({
                            "backup_path": info.path,
                            "backup_file": os.path.join(info.path, rel),
                            "original_path": orig,
                            "created_at": info.created_at,
                        })
            snapshots.append({
                "path": info.path,
                "created_at": info.created_at,
                "verified": info.verified,
                "has_state_db": has_state_db,
                "sessions": sessions,
            })
        return snapshots

    # ---------------- 诊断 ----------------

    def diagnose(self) -> VisibilityReport:
        db_rows, _db_path = self._read_db()
        session_files = self._scan_session_files()
        index = self._read_index()
        trash_entries = {e.id.lower(): e for e in self._trash.list_entries()}
        trash_rollout = {
            tid for tid, e in trash_entries.items()
            if os.path.isfile(os.path.join(self._trash._root, e.id, "rollout.jsonl"))
        }
        backups = self._load_backups()

        # 备份中的会话（按备份时间倒序取最新可用）
        backup_sessions: dict = {}
        for snap in backups:
            for tid, items in snap["sessions"].items():
                if tid not in backup_sessions:
                    backup_sessions[tid] = items[-1] if items else None

        all_ids = set(db_rows) | set(session_files) | set(index) | set(trash_entries)
        for snap in backups:
            all_ids |= set(snap["sessions"])

        current_provider = None
        try:
            current_provider, _model, _providers, _errs, _warns = read_config(self._codex_path)
        except Exception:
            current_provider = None

        findings: list = []

        # 整库回退候选：当前数据库为空/缺失，但备份里存在完整会话
        if not db_rows:
            candidates = [s for s in backups if s["verified"] and s["sessions"] and s["has_state_db"]]
            if candidates:
                newest = candidates[0]
                findings.append(VisibilityFinding(
                    kind="whole_db_restore",
                    risk="high",
                    summary="当前数据库为空，但备份 %s 包含完整会话" % newest["created_at"],
                    detail="从该备份整体恢复会回退备份之后产生的所有变更"
                           "（其他会话的最新状态、归档状态、索引等），请谨慎确认。",
                    suggestion="从备份整体恢复（高风险，需明确确认）",
                    source="backup",
                    payload={"backup_path": newest["path"]},
                ))

        for tid in sorted(all_ids):
            in_db = tid in db_rows
            in_file = tid in session_files
            in_index = tid in index
            in_trash = tid in trash_entries and tid in trash_rollout
            in_backup = tid in backup_sessions and backup_sessions[tid] is not None

            if in_db and in_file and in_index and not in_trash:
                continue  # 数据齐全

            if in_db and not in_file:
                if in_trash:
                    findings.append(VisibilityFinding(
                        thread_id=tid, kind="missing_session", risk="low",
                        summary="会话文件在废纸篓中",
                        detail="数据库有记录，但会话文件被移入了废纸篓；从废纸篓恢复即可。",
                        suggestion="从废纸篓恢复会话文件",
                        source="trash",
                    ))
                elif in_backup:
                    b = backup_sessions[tid]
                    findings.append(VisibilityFinding(
                        thread_id=tid, kind="missing_session", risk="medium",
                        summary="会话文件缺失，备份 %s 中存在" % b["created_at"],
                        detail="仅恢复该会话文件，不回退其他数据。",
                        suggestion="从备份恢复该会话文件",
                        source="backup",
                        payload=b,
                    ))
                else:
                    findings.append(VisibilityFinding(
                        thread_id=tid, kind="missing_session", risk="low",
                        summary="会话文件缺失且无可用备份",
                        detail="数据库行不是对话内容；会话文件不存在时补行不会恢复对话，"
                               "仅建议保留记录或后续清理。",
                        suggestion="无可恢复内容（保留记录或清理）",
                        source="db",
                    ))

            if in_file and not in_db:
                findings.append(VisibilityFinding(
                    thread_id=tid, kind="missing_db_row", risk="medium",
                    summary="会话文件存在，但数据库没有记录",
                    detail="真实对话内容仍在，只是索引缺失；重建数据库记录即可恢复可见。",
                    suggestion="根据会话文件重建数据库记录",
                    source="session",
                    payload={"session_path": session_files[tid]},
                ))

            if in_db and in_file and not in_index:
                findings.append(VisibilityFinding(
                    thread_id=tid, kind="missing_index", risk="low",
                    summary="数据库与会话文件都在，但索引缺失",
                    detail="补一条 session_index 记录即可。",
                    suggestion="补索引",
                    source="index",
                ))

            if in_trash and not (in_db and in_file):
                findings.append(VisibilityFinding(
                    thread_id=tid, kind="in_trash", risk="medium",
                    summary="对话在废纸篓中，不在当前数据中",
                    detail="废纸篓里有完整会话文件与元数据。",
                    suggestion="从废纸篓恢复对话",
                    source="trash",
                ))

            if in_backup and not (in_db or in_file or in_index) and not in_trash:
                b = backup_sessions[tid]
                findings.append(VisibilityFinding(
                    thread_id=tid, kind="in_backup_only", risk="medium",
                    summary="对话仅存在于备份 %s" % b["created_at"],
                    detail="当前数据中完全没有该会话，可从备份恢复会话文件并重建记录。",
                    suggestion="从备份恢复会话并重建记录",
                    source="backup",
                    payload=b,
                ))

        # 孤儿索引（索引里有、数据库和文件都没有）
        orphan_ids = sorted(set(index) - set(db_rows) - set(session_files))
        for tid in orphan_ids:
            findings.append(VisibilityFinding(
                thread_id=tid, kind="index_orphan", risk="low",
                summary="索引中存在孤儿条目",
                detail="该条目没有对应的数据库记录或会话文件。",
                suggestion="删除孤儿索引条目",
                source="index",
            ))

        # Provider 不一致：应用侧栏按会话文件首行的 model_provider 过滤，
        # 与当前 provider 不一致的对话会被侧栏隐藏（这是"侧栏看不到对话"的根因）。
        if current_provider:
            mismatched = []
            for tid, path in session_files.items():
                prov = self._session_meta_provider(path)
                if prov and prov != current_provider:
                    mismatched.append((tid, path, prov))
            if mismatched:
                providers = sorted({p for _t, _p, p in mismatched})
                findings.append(VisibilityFinding(
                    kind="provider_mismatch",
                    risk="medium",
                    summary="%d 个会话文件的 provider（%s）与当前 provider（%s）不一致，侧栏会隐藏它们" % (
                        len(mismatched), "、".join(providers), current_provider),
                    detail="Codex 侧栏按会话文件首行的 model_provider 过滤对话；"
                           "把它们对齐到当前 provider 后重启 Codex，对话即可全部显示。",
                    suggestion="把会话文件 provider 对齐到当前 provider 并同步数据库",
                    source="session",
                    payload={"current_provider": current_provider, "count": len(mismatched)},
                ))

        # 去重（同一 id + kind 只保留一条）
        seen = set()
        unique = []
        for f in findings:
            key = (f.thread_id, f.kind)
            if key in seen:
                continue
            seen.add(key)
            unique.append(f)
        unique.sort(key=lambda f: (EXECUTION_ORDER.get(f.kind, 50), f.thread_id))

        n_content = sum(1 for f in unique if f.kind in ("missing_session", "in_trash", "in_backup_only"))
        n_struct = sum(1 for f in unique if f.kind in ("missing_index", "index_orphan", "missing_db_row", "provider_mismatch"))
        n_high = sum(1 for f in unique if f.risk == "high")
        summary = "检测到 %d 条可见性问题：%d 条与会话内容相关，%d 条与索引/路径/Provider 相关，高风险整库恢复 %d 条。" % (
            len(unique), n_content, n_struct, n_high)
        n_prefix = sum(
            1 for r in db_rows.values()
            if r.get("rollout_path", "").startswith("\\\\?\\")
        )
        if n_prefix:
            summary += " 另有 %d 条路径带 \\\\?\\ 前缀（Codex 正常写法，无需修复）。" % n_prefix

        return VisibilityReport(
            codex_path=self._codex_path,
            findings=unique,
            summary=summary,
            has_high_risk=n_high > 0,
        )

    # ---------------- 执行（确认后） ----------------

    def execute(self, report: VisibilityReport, kinds: list[str] | None = None) -> dict:
        """执行选中的修复项。必须先备份，再按优先级应用。"""
        if self.is_codex_running():
            return {"ok": False, "message": "Codex 正在运行，请先完全退出 Codex 再执行修复。"}

        before = len(self._read_db()[0])
        backup_info = self._backup_svc.create_backup()

        chosen = [f for f in report.findings if kinds is None or f.kind in kinds]
        chosen.sort(key=lambda f: EXECUTION_ORDER.get(f.kind, 50))
        applied: list[str] = []

        for f in chosen:
            try:
                self._apply(f)
                applied.append("%s (%s)" % (f.kind, f.thread_id or "-"))
            except Exception as e:
                applied.append("%s (%s) 失败: %s" % (f.kind, f.thread_id or "-", e))

        after = len(self._read_db()[0])
        return {
            "ok": True,
            "backup_path": backup_info.path,
            "before": before,
            "after": after,
            "applied": applied,
        }

    def _apply(self, f: VisibilityFinding) -> None:
        if f.kind == "missing_session":
            if f.source == "trash":
                rr = self._trash.restore(f.thread_id, self._codex_path)
                if not rr.ok:
                    raise RuntimeError(rr.error or "废纸篓恢复失败")
            elif f.source == "backup":
                src = f.payload["backup_file"]
                dst = f.payload["original_path"]
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                if f.thread_id and f.thread_id not in self._read_db()[0]:
                    self._rebuild_db_row(dst, f.thread_id)
                if f.thread_id and f.thread_id not in self._read_index():
                    self._append_index(f.thread_id)
            # 无可恢复内容时为空操作
        elif f.kind == "in_trash":
            rr = self._trash.restore(f.thread_id, self._codex_path)
            if not rr.ok:
                raise RuntimeError(rr.error or "废纸篓恢复失败")
        elif f.kind == "in_backup_only" and f.source == "backup":
            src = f.payload["backup_file"]
            dst = f.payload["original_path"]
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            if f.thread_id and f.thread_id not in self._read_db()[0]:
                self._rebuild_db_row(dst, f.thread_id)
            if f.thread_id and f.thread_id not in self._read_index():
                self._append_index(f.thread_id)
        elif f.kind == "missing_db_row":
            self._rebuild_db_row(f.payload["session_path"], f.thread_id)
            if f.thread_id and f.thread_id not in self._read_index():
                self._append_index(f.thread_id)
        elif f.kind == "missing_index":
            self._append_index(f.thread_id)
        elif f.kind == "provider_mismatch":
            self._align_provider(f.payload.get("current_provider"))
        elif f.kind == "index_orphan":
            self._remove_orphan_index()
        elif f.kind == "whole_db_restore":
            rr = self._backup_svc.restore_full(f.payload["backup_path"])
            if not rr.success:
                raise RuntimeError("整体恢复失败")
        else:
            raise RuntimeError("未知修复类型: %s" % f.kind)

    def _align_provider(self, current_provider: str) -> None:
        """把会话文件首行的 model_provider 对齐到当前 provider，并同步数据库列。"""
        if not current_provider:
            return
        changed: list[str] = []
        for tid, path in self._scan_session_files().items():
            prov = self._session_meta_provider(path)
            if prov and prov != current_provider:
                self._rewrite_session_provider(path, current_provider)
                changed.append(tid)
        if changed:
            db_path = find_state_db(self._codex_path)
            if db_path:
                con = sqlite3.connect(db_path, timeout=30)
                try:
                    con.executemany(
                        "UPDATE threads SET model_provider=? WHERE id=?",
                        [(current_provider, tid) for tid in changed],
                    )
                    con.commit()
                finally:
                    con.close()

    @staticmethod
    def _session_meta_provider(session_path: str) -> str:
        """读取会话文件首行 session_meta 的 model_provider。"""
        try:
            with open(session_path, "r", encoding="utf-8-sig", errors="replace") as f:
                first = f.readline()
            obj = json.loads(first)
            payload = obj.get("payload") if isinstance(obj, dict) else None
            if isinstance(payload, dict):
                return str(payload.get("model_provider") or "")
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return ""

    @staticmethod
    def _rewrite_session_provider(session_path: str, current_provider: str) -> None:
        """只改写会话文件首行（session_meta）的 model_provider，其余字节原样保留。"""
        with open(session_path, "rb") as f:
            data = f.read()
        nl = data.find(b"\n")
        if nl == -1:
            return
        first = data[:nl]
        rest = data[nl:]
        try:
            obj = json.loads(first.decode("utf-8", errors="replace"))
            payload = obj.get("payload") if isinstance(obj, dict) else None
            if not isinstance(payload, dict):
                return
            payload["model_provider"] = current_provider
        except (json.JSONDecodeError, ValueError):
            return
        new_first = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with open(session_path, "wb") as f:
            f.write(new_first + rest)

    # ---------------- 底层修复动作 ----------------

    def _rebuild_db_row(self, session_path: str, thread_id: str) -> None:
        meta = self._read_session_meta(session_path)
        db_path = find_state_db(self._codex_path)
        if not db_path:
            raise RuntimeError("未找到 state_*.sqlite")
        con = sqlite3.connect(db_path, timeout=30)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(threads)")]
            values = {
                "id": thread_id,
                "rollout_path": session_path,
                "title": meta.get("title", "") or "(no title)",
                "model_provider": meta.get("model_provider", ""),
                "archived": 0,
                "created_at_ms": meta.get("created_at_ms", 0),
                "updated_at_ms": meta.get("updated_at_ms", 0),
                "source": meta.get("source", "vscode"),
                "cwd": meta.get("cwd", ""),
                "tokens_used": 0,
            }
            if "thread_source" in cols and meta.get("thread_source"):
                values["thread_source"] = meta["thread_source"]
            if "first_user_message" in cols:
                values["first_user_message"] = values["title"]
            if "cli_version" in cols and meta.get("cli_version"):
                values["cli_version"] = meta["cli_version"]
            present = [c for c in values if c in cols]
            ph = ",".join("?" for _ in present)
            con.execute(
                "INSERT OR REPLACE INTO threads (%s) VALUES (%s)" % (", ".join(present), ph),
                [values[c] for c in present],
            )
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _read_session_meta(session_path: str) -> dict:
        """从 rollout 首行 session_meta 与首条用户消息提取标题/字段。"""
        meta = {}
        with open(session_path, "r", encoding="utf-8-sig", errors="replace") as f:
            first = f.readline()
        try:
            obj = json.loads(first)
            payload = obj.get("payload", {}) if isinstance(obj, dict) else {}
            meta.update({
                "model_provider": payload.get("model_provider", ""),
                "cwd": payload.get("cwd", ""),
                "source": payload.get("source", ""),
                "thread_source": payload.get("thread_source", ""),
                "cli_version": payload.get("cli_version", ""),
            })
            ts = payload.get("timestamp") or obj.get("timestamp")
            meta["created_at_ms"] = _parse_iso_ms(ts)
        except (json.JSONDecodeError, ValueError):
            pass
        meta["updated_at_ms"] = int(os.path.getmtime(session_path) * 1000)
        meta["title"] = _extract_title(session_path, limit=500)
        return meta

    def _append_index(self, thread_id: str) -> None:
        idx_path = os.path.join(self._codex_path, "session_index.jsonl")
        title = ""
        db_rows, _ = self._read_db()
        if thread_id in db_rows:
            title = db_rows[thread_id].get("title") or ""
        line = json.dumps({
            "id": thread_id,
            "thread_name": title[:60] if title else "",
            "updated_at": datetime.now().isoformat() + "Z",
        }, ensure_ascii=False) + "\n"
        with open(idx_path, "a", encoding="utf-8") as f:
            f.write(line)

    def _remove_orphan_index(self) -> None:
        idx_path = os.path.join(self._codex_path, "session_index.jsonl")
        if not os.path.isfile(idx_path):
            return
        db_rows, _ = self._read_db()
        kept = []
        with open(idx_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    oid = json.loads(line).get("id", "").lower()
                except json.JSONDecodeError:
                    oid = ""
                if oid in db_rows:
                    kept.append(line)
        tmp = idx_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, idx_path)

    def _normalize_path(self, thread_id: str) -> None:
        db_path = find_state_db(self._codex_path)
        if not db_path:
            return
        con = sqlite3.connect(db_path, timeout=30)
        try:
            row = con.execute("SELECT rollout_path FROM threads WHERE id=?", (thread_id,)).fetchone()
            if not row:
                return
            current = row[0] or ""
            normalized = current[4:] if current.startswith("\\\\?\\") else current
            if normalized != current:
                con.execute("UPDATE threads SET rollout_path=? WHERE id=?",
                            (normalized, thread_id))
                con.commit()
        finally:
            con.close()


def _parse_iso_ms(value) -> int:
    """把 ISO 时间字符串转毫秒时间戳；失败返回 0。"""
    if not value:
        return 0
    try:
        from datetime import datetime
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def _extract_title(session_path: str, limit: int = 500) -> str:
    """从 rollout 前若干行提取首条用户文本作为标题。"""
    candidates = []
    with open(session_path, "r", encoding="utf-8-sig", errors="replace") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            if '"text"' not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            def walk(x):
                if isinstance(x, dict):
                    if x.get("type") in ("user", "message") and isinstance(x.get("text"), str):
                        candidates.append(x["text"])
                    if isinstance(x.get("payload"), dict) and x["payload"].get("type") == "user":
                        items = x["payload"].get("items") or []
                        for it in items:
                            if isinstance(it, dict) and isinstance(it.get("text"), str):
                                candidates.append(it["text"])
                    for v in x.values():
                        walk(v)
                elif isinstance(x, list):
                    for v in x:
                        walk(v)

            walk(obj)
            if candidates:
                break
    text = candidates[0] if candidates else ""
    return text.replace("\r", " ").replace("\n", " ").strip()[:60]
