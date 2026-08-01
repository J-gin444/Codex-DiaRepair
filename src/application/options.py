"""用户配置与修复选项。GUI 和 CLI 通过此层传递用户决策。"""

from dataclasses import dataclass, field


@dataclass
class ProviderMapping:
    """缺失 provider 的修复策略。"""
    source_provider: str          # 历史中出现的 provider 名称
    mode: str = "alias"           # alias | delete | keep
    target_provider: str = ""     # mode=alias 时映射到的现有 provider
    base_url: str = ""            # 新增 provider 时的 base_url


@dataclass
class DeletePolicy:
    """失效会话的清理策略。"""
    mode: str = "trash"           # trash | permanent | keep_reference
    trash_dir: str = ""           # 移入废纸篓的目录


@dataclass
class BackupConfig:
    """备份配置。"""
    directory: str = ""
    retention: int = 5            # 保留的备份数量
    compress: bool = False


@dataclass
class RepairOptions:
    """用户对修复操作的全部配置。

    传递给 Planner 和 Executor，影响计划生成和执行策略。
    """
    provider_mappings: list[ProviderMapping] = field(default_factory=list)
    delete_policy: DeletePolicy = field(default_factory=DeletePolicy)
    backup: BackupConfig = field(default_factory=BackupConfig)
    auto_confirm: bool = False    # 跳过确认，执行所有 auto+confirm action


def default_backup_root() -> str:
    """返回稳定的备份根目录（不依赖进程当前工作目录）。

    优先使用 %LOCALAPPDATA%，保证双击 exe 时也可写。
    """
    import os
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DiaRepair", "备份")
