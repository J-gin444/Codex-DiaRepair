"""Scanner 模块的数据模型定义。

基于 docs/data-model.md 定义的稳定数据模型。
所有数据类使用 dataclass，字段名和类型与文档保持一致。
"""

from dataclasses import dataclass, field
from enum import Enum



class ProviderSource(Enum):
    CONFIG = "config"
    BUILTIN = "builtin"
    HISTORY_ONLY = "history"
    USER_DEFINED = "user"
    UNKNOWN = "unknown"

class ProviderStatus(Enum):
    AVAILABLE = "available"
    MISSING_CONFIG = "missing_config"
    AUTH_MANAGED = "auth_managed"

@dataclass
class AuthState:
    """认证/登录状态（只读取模式标记，不包含任何敏感凭据）。

    用于区分"本地数据损坏"与"认证模式导致同步失效"两类问题。
    """
    forced_login_method: str = ""           # config.toml 顶层 forced_login_method
    preferred_auth_method: str = ""         # config.toml 顶层 preferred_auth_method
    disable_response_storage: bool = False  # config.toml 顶层 disable_response_storage
    cached_auth_mode: str = ""              # auth.json 的 auth_mode（如 chatgpt / apikey）
    has_cached_chatgpt_tokens: bool = False  # auth.json 是否缓存了 ChatGPT 账号 token
    config_path: str = ""
    auth_json_path: str = ""

@dataclass
class ProviderInfo:
    """config.toml 中 [model_providers.xxx] 段的解析结果。"""
    section_name: str      # 节名，如 "custom"
    name: str = ""         # 供应商显示名称
    base_url: str = ""     # API 基础地址
    wire_api: str = ""     # API 协议类型
    requires_openai_auth: bool = False
    experimental_bearer_token: str = ""
    raw_section: str = ""  # 原始配置块文本（用于别名生成）


@dataclass
class ThreadInfo:
    """state_5.sqlite.threads 表中的一条对话记录。"""
    id: str                     # UUID v7
    title: str = ""             # 原始标题
    title_short: str = ""       # 截断至 60 字符的标题
    provider: str = ""          # model_provider 字段值
    rollout_path: str = ""      # 原始路径（可能含 \\\\?\\）
    normalized_path: str = ""   # 规范化后的路径
    size_bytes: int = 0         # 会话文件磁盘大小
    size_label: str = ""        # 格式化后的大小字符串
    updated_at_ms: int = 0      # 毫秒时间戳
    updated_label: str = ""     # 格式化为 "YYYY-MM-DD HH:MM"
    archived: bool = False
    created_at_ms: int = 0
    source: str = ""
    cwd: str = ""
    tokens_used: int = 0


@dataclass
class GoalInfo:
    """goals_1.sqlite.thread_goals 表中的一条目标记录。"""
    thread_id: str
    goal_id: str
    objective: str = ""
    status: str = ""


@dataclass
class SessionIndexEntry:
    """session_index.jsonl 中的一条索引记录。"""
    id: str
    thread_name: str = ""
    updated_at: str = ""


@dataclass
class ScanDiagnostics:
    """扫描诊断结果。"""
    # Provider 相关
    provider_defined: bool = True           # 当前 provider 在 [model_providers] 中是否有定义
    provider_defined_names: list[str] = field(default_factory=list)  # 所有已定义的 provider 名称

    # 不一致统计
    missing_history_providers: list[str] = field(default_factory=list)  # 历史存在但 config 缺失的 provider
    db_non_current: int = 0                # 数据库中 provider != current_provider 的记录数
    jsonl_non_current: int = 0             # 会话文件中 provider != current_provider 的记录数

    # session_index.jsonl 一致性
    session_index_total: int = 0
    session_index_matched: int = 0         # 与 threads 匹配的数量
    session_index_unmatched: int = 0       # 与 threads 不匹配的数量

    # 路径规范化
    rollout_paths_with_prefix: int = 0; project_cwds: list[str] = field(default_factory=list); project_thread_counts: dict[str, int] = field(default_factory=dict)     # 含 \\\\?\\ 前缀的路径数


@dataclass
class ScanResult:
    """扫描的完整输出，聚合所有数据源的信息。"""
    # 元信息
    codex_home: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # 配置
    current_provider: str | None = None
    current_model: str | None = None
    defined_providers: dict[str, ProviderInfo] = field(default_factory=dict)
    auth: AuthState = field(default_factory=AuthState)

    # 线程列表（聊天记录）
    active_threads: list[ThreadInfo] = field(default_factory=list)
    archived_threads: list[ThreadInfo] = field(default_factory=list)
    thread_list: list[ThreadInfo] = field(default_factory=list)

    # 目标
    goals: dict[str, list[GoalInfo]] = field(default_factory=dict)  # thread_id -> goals

    # 统计
    db_provider_distribution: dict[str, int] = field(default_factory=dict)
    jsonl_provider_distribution: dict[str, int] = field(default_factory=dict)
    session_index_entries: list[SessionIndexEntry] = field(default_factory=list)
    jsonl_files_scanned: int = 0
    total_memory_bytes: int = 0

    # 诊断
    diagnostics: ScanDiagnostics = field(default_factory=ScanDiagnostics)


@dataclass
class ScanStats:
    """扫描统计摘要，用于日志和界面展示。"""
    active_count: int = 0
    archived_count: int = 0
    total_threads: int = 0
    jsonl_files_scanned: int = 0
    total_memory_bytes: int = 0
    memory_label: str = ""
    provider_distribution: dict[str, int] = field(default_factory=dict)
