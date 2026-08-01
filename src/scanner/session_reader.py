"""会话文件扫描模块。

负责扫描 sessions/ 和 archived_sessions/ 目录下的 NDJSON 文件，
以及读取 session_index.jsonl。
"""

import json
import os
from .models import SessionIndexEntry
from .exceptions import SessionFileError


def scan_session_files(codex_home: str) -> tuple[dict[str, int], int, list[str]]:
    """扫描所有会话文件 (sessions/ 和 archived_sessions/)。

    读取每个 .jsonl 文件的首行 session_meta，提取 model_provider。
    只解析首行，不遍历完整对话事件。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        (provider_distribution, files_scanned, warnings)
        provider_distribution: {provider_name: count}
        files_scanned: 扫描的会话文件总数
        warnings: 单文件解析失败等警告
    """
    provider_dist: dict[str, int] = {}
    files_scanned = 0
    warnings: list[str] = []

    sessions_root = os.path.join(codex_home, "sessions")
    archived_root = os.path.join(codex_home, "archived_sessions")

    for root_dir in (sessions_root, archived_root):
        if not os.path.isdir(root_dir):
            warnings.append("Directory not found: %s" % os.path.basename(root_dir))
            continue

        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for filename in filenames:
                if not filename.endswith(".jsonl"):
                    continue
                filepath = os.path.join(dirpath, filename)
                provider = _read_session_meta_provider(filepath)
                files_scanned += 1
                if provider is not None:
                    provider_dist[provider] = provider_dist.get(provider, 0) + 1

    return provider_dist, files_scanned, warnings


def _read_session_meta_provider(filepath: str) -> str | None:
    """读取会话文件首行的 model_provider。

    Args:
        filepath: .jsonl 文件路径。

    Returns:
        model_provider 的值，如果读取失败或类型不匹配返回 None。
    """
    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            first_line = f.readline()
    except OSError:
        return None

    if not first_line.strip():
        return None

    try:
        obj = json.loads(first_line)
    except json.JSONDecodeError:
        return None

    if not isinstance(obj, dict):
        return None
    if obj.get("type") != "session_meta":
        return None

    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None

    return payload.get("model_provider")


def read_session_index(codex_home: str) -> tuple[list[SessionIndexEntry], list[str]]:
    """读取 session_index.jsonl。

    只提取已确认的字段：id、thread_name、updated_at。
    不假设 model_provider 或 rollout_path 存在。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        (entries, warnings)
        entries: SessionIndexEntry 列表
        warnings: 行解析失败的警告
    """
    index_path = os.path.join(codex_home, "session_index.jsonl")
    if not os.path.isfile(index_path):
        return [], ["session_index.jsonl not found"]

    entries: list[SessionIndexEntry] = []
    warnings: list[str] = []

    try:
        with open(index_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append("session_index.jsonl line %d: JSON parse failed" % line_no)
                    continue

                if not isinstance(obj, dict):
                    warnings.append("session_index.jsonl line %d: not a JSON object" % line_no)
                    continue

                entries.append(SessionIndexEntry(
                    id=obj.get("id", ""),
                    thread_name=obj.get("thread_name", ""),
                    updated_at=obj.get("updated_at", ""),
                ))
    except OSError as e:
        warnings.append("Failed to read session_index.jsonl: %s" % e)

    return entries, warnings
