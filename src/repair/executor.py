"""RepairExecutor: 执行 RepairPlan 中的 Action。"""

import json, os, re, sqlite3
from .models import (
    RepairAction, RepairPlan, BackupSnapshot, Precondition, RepairStatus,
    ActionExecutionStatus, ActionResult, RepairExecutionResult,
)

def execute(plan: RepairPlan, snapshot: BackupSnapshot | None) -> RepairExecutionResult:
    if snapshot is None:
        return RepairExecutionResult(status=RepairStatus.FAILED, summary="No BackupSnapshot.")
    if not plan.actions:
        return RepairExecutionResult(status=RepairStatus.COMPLETED, snapshot=snapshot, summary="No actions.")

    results = []
    success = failed = skipped = 0
    for action in plan.actions:
        ar = ActionResult(action_type=action.action_type, thread_id=action.thread_id, status=ActionExecutionStatus.RUNNING)
        if action.requires_confirmation:
            ar.status = ActionExecutionStatus.SKIPPED
            ar.message = "requires confirmation"
            results.append(ar); skipped += 1; continue
        precond_ok, precond_msg = _check_preconditions(action, snapshot)
        if not precond_ok:
            ar.status = ActionExecutionStatus.SKIPPED
            ar.message = "precondition: %s" % precond_msg
            results.append(ar); skipped += 1; continue
        handler = _HANDLERS.get(action.action_type)
        if handler is None:
            ar.status = ActionExecutionStatus.SKIPPED
            ar.message = "unknown action_type: %s" % action.action_type
            results.append(ar); skipped += 1; continue
        try:
            handler(action, snapshot)
            ar.status = ActionExecutionStatus.SUCCESS; ar.message = "ok"; success += 1
        except Exception as e:
            ar.status = ActionExecutionStatus.FAILED; ar.message = str(e); failed += 1
        results.append(ar)

    return RepairExecutionResult(
        status=RepairStatus.FAILED if failed > 0 else RepairStatus.COMPLETED,
        snapshot=snapshot, action_results=results,
        success_count=success, failed_count=failed, skipped_count=skipped,
        summary="%d success, %d failed, %d skipped" % (success, failed, skipped),
    )

def _check_preconditions(action: RepairAction, snapshot) -> tuple[bool, str]:
    for pc in action.preconditions:
        if pc == Precondition.THREAD_EXISTS and not action.thread_id:
            return False, "empty thread_id"
        if pc == Precondition.CONFIG_EXISTS:
            cfg = _resolve_target("config.toml", snapshot)
            if not os.path.isfile(cfg):
                return False, "config.toml not found"
    return True, ""

# ============ Handlers ============

def _remove_orphan_index(action, snapshot):
    index_path = _resolve_target("session_index.jsonl", snapshot)
    if not os.path.isfile(index_path): return

    # 孤儿 = session_index 中存在、但 state_*.sqlite.threads 中不存在的条目
    db_path = _resolve_target("state_5.sqlite", snapshot)
    known_ids: set[str] = set()
    if os.path.isfile(db_path):
        try:
            con = sqlite3.connect(db_path, timeout=30)
            known_ids = {r[0] for r in con.execute("SELECT id FROM threads")}
            con.close()
        except sqlite3.Error:
            known_ids = set()

    with open(index_path, "r", encoding="utf-8-sig") as f:
        entries = [line for line in f if line.strip()]
    if not entries: return

    kept = [line for line in entries if _jsonl_id(line) in known_ids]
    tmp = index_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.writelines(kept)
    os.replace(tmp, index_path)

def _normalize_path(action, snapshot):
    db_path = _resolve_target("state_5.sqlite", snapshot)
    con = sqlite3.connect(db_path, timeout=30)
    try:
        cur = con.execute("SELECT rollout_path FROM threads WHERE id=?", (action.thread_id,))
        row = cur.fetchone()
        if not row: raise RuntimeError("thread not found")
        current = row[0] or ""
        normalized = current
        if normalized.startswith("\\\\?\\"): normalized = normalized[4:]
        if normalized == current: return
        con.execute("UPDATE threads SET rollout_path=? WHERE id=?", (normalized, action.thread_id))
        con.commit()
    finally:
        con.close()

def _delete_threads(action, snapshot):
    thread_ids = [tid.strip() for tid in action.thread_id.split(",") if tid.strip()]
    if not thread_ids: return
    db_path = _resolve_target("state_5.sqlite", snapshot)
    goals_path = _resolve_target("goals_1.sqlite", snapshot)
    index_path = _resolve_target("session_index.jsonl", snapshot)

    con = sqlite3.connect(db_path, timeout=30)
    try:
        ph = ",".join("?" for _ in thread_ids)
        con.execute("DELETE FROM thread_dynamic_tools WHERE thread_id IN (%s)" % ph, thread_ids)
        con.execute("DELETE FROM thread_spawn_edges WHERE parent_thread_id IN (%s) OR child_thread_id IN (%s)" % (ph, ph), thread_ids + thread_ids)
        deleted = con.execute("DELETE FROM threads WHERE id IN (%s)" % ph, thread_ids).rowcount
        con.commit()
    finally:
        con.close()

    if os.path.isfile(goals_path):
        c2 = sqlite3.connect(goals_path, timeout=30)
        try:
            ph = ",".join("?" for _ in thread_ids)
            c2.execute("DELETE FROM thread_goals WHERE thread_id IN (%s)" % ph, thread_ids)
            c2.commit()
        except Exception: pass
        finally: c2.close()

    if os.path.isfile(index_path):
        keep = set(thread_ids)
        tmp = index_path + ".tmp"
        with open(index_path, "r", encoding="utf-8-sig") as f:
            kept_lines = [l for l in f if _jsonl_id(l) not in keep]
        with open(tmp, "w", encoding="utf-8") as f: f.writelines(kept_lines)
        os.replace(tmp, index_path)

    if deleted == 0: raise RuntimeError("no threads matched")

def _jsonl_id(line):
    try: return json.loads(line.strip()).get("id", "")
    except: return ""

def _cleanup_invalid_thread(action, snapshot):
    raise RuntimeError("cleanup_invalid_thread not implemented in MVP")


_AUTH_KEYS_TO_REMOVE = ("forced_login_method", "preferred_auth_method")


def _restore_account_auth(action, snapshot):
    """移除 config.toml 顶层强制 API 登录的键，恢复 ChatGPT 账号登录。

    只删除顶层 key = value 行（不在任何 [section] 内），保留其余配置；
    使用 tmp + os.replace 原子替换，未命中任何键时视为幂等成功。
    """
    cfg = _resolve_target("config.toml", snapshot)
    if not os.path.isfile(cfg):
        raise RuntimeError("config.toml not found")

    with open(cfg, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = f.read().splitlines(keepends=True)

    in_section = False
    removed = 0
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\[.+\]$", stripped):
            in_section = True
            kept.append(line)
            continue
        if in_section:
            kept.append(line)
            continue
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue
        kv = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=", stripped)
        if kv and kv.group(1) in _AUTH_KEYS_TO_REMOVE:
            removed += 1
            continue
        kept.append(line)

    if removed == 0:
        return  # 幂等：没有需要移除的键

    tmp = cfg + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.writelines(kept)
    os.replace(tmp, cfg)


def _resolve_target(name, snapshot):
    for bf in snapshot.files:
        if os.path.basename(bf.original_path) == name: return bf.original_path
    return os.path.join(snapshot.source, name)

_HANDLERS = {
    "remove_orphan_index": _remove_orphan_index,
    "normalize_path": _normalize_path,
    "delete_thread": _delete_threads,
    "cleanup_invalid_thread": _cleanup_invalid_thread,
    "restore_account_auth": _restore_account_auth,
}
