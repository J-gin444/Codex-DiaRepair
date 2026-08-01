"""Codex Repair Tool — Scanner 模块。

提供 Codex 本地数据目录的完整扫描能力。
所有输出为结构化数据，不依赖 Tkinter 或 GUI。
"""

from src.scanner.scanner import scan_codex_home, compute_stats
from src.scanner.auth_reader import read_auth_state
from src.scanner.models import (
    ScanResult,
    ScanDiagnostics,
    ScanStats,
    AuthState,
    ThreadInfo,
    ProviderInfo,
    GoalInfo,
    SessionIndexEntry,
)
from src.scanner.normalizer import normalize_rollout_path

__all__ = [
    "scan_codex_home",
    "compute_stats",
    "read_auth_state",
    "ScanResult",
    "ScanDiagnostics",
    "ScanStats",
    "AuthState",
    "ThreadInfo",
    "ProviderInfo",
    "GoalInfo",
    "SessionIndexEntry",
    "normalize_rollout_path",
]
