"""SQLite 数据库读取模块。

负责读取 state_5.sqlite 和 goals_1.sqlite。
自动识别 state_*.sqlite 文件（不硬编码版本号）。
所有数据库连接使用只读模式 (mode=ro)。
"""

import glob
import os
import sqlite3
from .models import ThreadInfo, GoalInfo
from .normalizer import normalize_rollout_path
from .exceptions import DatabaseError


def find_state_db(codex_home: str) -> str | None:
    """自动查找 state_*.sqlite 文件。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        匹配的 state 数据库路径，或 None。
    """
    pattern = os.path.join(codex_home, "state_*.sqlite")
    matches = [f for f in glob.glob(pattern) if not f.endswith(("-wal", "-shm"))]
    if not matches:
        return None
    # 取最新的匹配
    matches.sort(key=os.path.getmtime, reverse=True)
    return matches[0]


def read_threads(codex_home: str) -> tuple[list[ThreadInfo], dict[str, int], list[str]]:
    """读取 state_*.sqlite 的 threads 表。

    只提取 Repair 相关的字段（不复制完整 schema）。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        (threads, provider_distribution, errors)
        threads: ThreadInfo 列表
        provider_distribution: {provider_name: count}
        errors: 错误信息列表
    """
    state_db = find_state_db(codex_home)
    if not state_db:
        db_pattern = os.path.join(codex_home, "state_*.sqlite")
        return [], {}, ["No state database found matching %s" % db_pattern]

    try:
        con = sqlite3.connect("file:%s?mode=ro" % state_db, uri=True, timeout=30)
    except sqlite3.Error as e:
        return [], {}, ["Failed to connect to %s: %s" % (os.path.basename(state_db), e)]

    threads: list[ThreadInfo] = []
    provider_dist: dict[str, int] = {}
    errors: list[str] = []

    try:
        _ensure_busy_timeout(con)

        # 线程列表查询（只提取 Repair 相关字段）
        query = """
            SELECT id, title, model_provider, updated_at_ms, archived,
                   rollout_path, created_at_ms, source, cwd, tokens_used
            FROM threads
            ORDER BY COALESCE(updated_at_ms, 0) DESC, COALESCE(updated_at, 0) DESC
        """
        rows = con.execute(query).fetchall()

        for row in rows:
            thread_id, title, provider, updated_ms, archived, \
                rollout_path, created_ms, source, cwd, tokens = row

            raw_path = rollout_path or ""
            norm_path = normalize_rollout_path(raw_path)

            # 会话文件实际大小
            try:
                size_bytes = os.path.getsize(norm_path) if norm_path else 0
            except OSError:
                size_bytes = 0

            threads.append(ThreadInfo(
                id=thread_id,
                title=title or "",
                title_short=_shorten_text(title or "(no title)", 60),
                provider=provider or "",
                rollout_path=raw_path,
                normalized_path=norm_path,
                size_bytes=size_bytes,
                size_label=_format_bytes(size_bytes),
                updated_at_ms=updated_ms or 0,
                updated_label=_format_timestamp_ms(updated_ms),
                archived=bool(archived),
                created_at_ms=created_ms or 0,
                source=source or "",
                cwd=cwd or "",
                tokens_used=tokens or 0,
            ))

        # provider 分布
        dist_rows = con.execute(
            "SELECT model_provider, COUNT(*) FROM threads GROUP BY model_provider"
        ).fetchall()
        for name, count in dist_rows:
            provider_dist[name or ""] = count

    except sqlite3.Error as e:
        errors.append("Database query failed (%s): %s" % (os.path.basename(state_db), e))
    finally:
        con.close()

    return threads, provider_dist, errors


def read_goals(codex_home: str) -> tuple[dict[str, list[GoalInfo]], list[str]]:
    """读取 goals_1.sqlite 的 thread_goals 表。

    注意：thread_goals 表不一定存在，数据库文件也不一定存在。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        (goals, errors)
        goals: {thread_id: [GoalInfo]}
        errors: 错误信息列表
    """
    goals_db = os.path.join(codex_home, "goals_1.sqlite")
    if not os.path.isfile(goals_db):
        return {}, []

    try:
        con = sqlite3.connect("file:%s?mode=ro" % goals_db, uri=True, timeout=30)
    except sqlite3.Error as e:
        return {}, ["Failed to connect to goals_1.sqlite: %s" % e]

    goals: dict[str, list[GoalInfo]] = {}
    errors: list[str] = []

    try:
        _ensure_busy_timeout(con)

        # 确认表存在
        table_exists = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='thread_goals'"
        ).fetchone()[0]

        if table_exists:
            rows = con.execute(
                "SELECT thread_id, goal_id, objective, status FROM thread_goals"
            ).fetchall()
            for row in rows:
                g = GoalInfo(
                    thread_id=row[0],
                    goal_id=row[1],
                    objective=row[2] or "",
                    status=row[3] or "",
                )
                goals.setdefault(g.thread_id, []).append(g)

    except sqlite3.Error as e:
        errors.append("Failed to read goals_1.sqlite: %s" % e)
    finally:
        con.close()

    return goals, errors


def _ensure_busy_timeout(con: sqlite3.Connection) -> None:
    """设置 busy_timeout。某些 WAL 模式数据库可能被 Codex 进程持有写锁。"""
    try:
        con.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass


# ---- 格式化工具函数 ----

def _shorten_text(text: str, limit: int = 60) -> str:
    """截断文本至指定长度。"""
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "..."


def _format_bytes(size: int | float) -> str:
    """格式化字节数。"""
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        value = 0.0
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return "%d B" % int(value)
            return "%.2f %s" % (value, unit)
        value /= 1024.0
    return "0 B"


def _format_timestamp_ms(ms: int | None) -> str:
    """格式化毫秒时间戳为可读字符串。"""
    if not ms:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromtimestamp(int(ms) / 1000.0)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)
