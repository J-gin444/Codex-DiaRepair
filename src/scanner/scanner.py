"""Scanner 模块：扫描编排主逻辑。

将所有子模块（config_reader、sqlite_reader、session_reader）
的扫描结果聚合为统一的 ScanResult。
"""

import os

from .models import ScanResult, ScanDiagnostics, ScanStats
from .config_reader import read_config
from .auth_reader import read_auth_state
from .sqlite_reader import read_threads, read_goals
from .session_reader import scan_session_files, read_session_index


def scan_codex_home(codex_home: str) -> ScanResult:
    """"扫描 Codex 本地数据目录，聚合所有数据源。

    扫描顺序：
    1. 验证目录存在
    2. 读取 config.toml
    3. 读取 state_*.sqlite
    4. 读取 goals_*.sqlite（如果存在）
    5. 扫描会话文件 (sessions/ + archived_sessions/)
    6. 读取 session_index.jsonl
    7. 计算诊断结果
    8. 聚合输出

    Args:
        codex_home: .codex 目录的完整路径。

    Returns:
        ScanResult: 包含所有数据源聚合结果的扫描结果。
    """
    result = ScanResult(codex_home=codex_home)
    diag = result.diagnostics

    # Step 1: 验证目录存在
    codex_home = os.path.abspath(os.path.expanduser(codex_home))
    result.codex_home = codex_home

    if not os.path.isdir(codex_home):
        result.errors.append(".codex directory not found: %s" % codex_home)
        return result

    # Step 2: 读取 config.toml
    current_provider, current_model, providers, cfg_errors, cfg_warnings = read_config(codex_home)
    result.current_provider = current_provider
    result.current_model = current_model
    result.defined_providers = providers
    result.errors.extend(cfg_errors)
    result.warnings.extend(cfg_warnings)

    # Step 2.5: 读取认证/登录状态（只读模式标记，不涉及数据修复链）
    result.auth = read_auth_state(codex_home)

    diag.provider_defined = bool(current_provider and current_provider in providers)
    diag.provider_defined_names = sorted(providers.keys())

    # Step 3: 读取 state_*.sqlite
    threads, provider_dist, db_errors = read_threads(codex_home)
    result.db_provider_distribution = provider_dist
    result.errors.extend(db_errors)

    # 分离活跃线程和归档线程
    for t in threads:
        if t.archived:
            result.archived_threads.append(t)
        else:
            result.active_threads.append(t)
    result.thread_list = threads

    # Step 4: 读取 goals_*.sqlite
    goals, goal_errors = read_goals(codex_home)
    result.goals = goals
    result.errors.extend(goal_errors)

    # Step 5: 扫描会话文件
    jsonl_dist, files_scanned, jl_warnings = scan_session_files(codex_home)
    result.jsonl_provider_distribution = jsonl_dist
    result.jsonl_files_scanned = files_scanned
    result.warnings.extend(jl_warnings)

    # Step 6: 读取 session_index.jsonl
    index_entries, idx_warnings = read_session_index(codex_home)
    result.session_index_entries = index_entries
    result.warnings.extend(idx_warnings)

    # session_index 匹配统计
    thread_ids = {t.id for t in threads}
    matched = sum(1 for e in index_entries if e.id in thread_ids)
    diag.session_index_total = len(index_entries)
    diag.session_index_matched = matched
    diag.session_index_unmatched = len(index_entries) - matched

    # rollout_path 前缀统计
        # project stats
    cwd_set = set()
    cwd_counts = {}
    for t in threads:
        c = t.cwd or "Unknown"
        cwd_set.add(c)
        cwd_counts[c] = cwd_counts.get(c, 0) + 1
    diag.project_cwds = sorted(cwd_set)
    diag.project_thread_counts = cwd_counts

    diag.rollout_paths_with_prefix = sum(
        1 for t in threads if t.rollout_path.startswith('\\\\?\\')
    )

    # Step 7: 计算诊断结果
    _compute_diagnostics(result)

    # Step 8: 计算总内存
    result.total_memory_bytes = sum(t.size_bytes for t in threads)

    return result


def _compute_diagnostics(result: ScanResult) -> None:
    """计算诊断结果。

    基于已收集的扫描结果，计算以下诊断：
    - missing_history_providers: 历史中出现但 config 未定义的 provider
    - db_non_current: 数据库中 provider 与当前不一致的记录数
    - jsonl_non_current: 会话文件中 provider 与当前不一致的记录数
    """
    diag = result.diagnostics
    current = result.current_provider
    defined = result.defined_providers

    # 收集所有历史 provider（数据库 + 会话文件）
    all_history_providers: set[str] = set()
    for name in result.db_provider_distribution:
        if name:
            all_history_providers.add(name)
    for name in result.jsonl_provider_distribution:
        if name:
            all_history_providers.add(name)

    # 缺失的历史 provider
    diag.missing_history_providers = sorted(
        name for name in all_history_providers
        if name and name not in defined
    )

    # 不一致统计
    if current:
        for name, count in result.db_provider_distribution.items():
            if name != current:
                diag.db_non_current += count
        for name, count in result.jsonl_provider_distribution.items():
            if name != current:
                diag.jsonl_non_current += count


def compute_stats(result: ScanResult) -> ScanStats:
    """从 ScanResult 生成统计摘要。"""
    return ScanStats(
        active_count=len(result.active_threads),
        archived_count=len(result.archived_threads),
        total_threads=len(result.thread_list),
        jsonl_files_scanned=result.jsonl_files_scanned,
        total_memory_bytes=result.total_memory_bytes,
        memory_label=_format_bytes(result.total_memory_bytes),
        provider_distribution=dict(result.db_provider_distribution),
    )


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
