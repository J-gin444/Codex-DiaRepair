"""Repair 模块的数据模型。Repair 只消费 DiagnosisResult + RepairContext。"""

from dataclasses import dataclass, field
from enum import Enum, auto
from ..diagnosis.models import IssueType


class Precondition(Enum):
    THREAD_EXISTS = "thread_exists"
    PATH_HAS_PREFIX = "path_has_prefix"
    SESSION_FILE_MISSING = "session_file_missing"
    CONFIG_EXISTS = "config_exists"
    PROVIDER_DEFINED_EXISTS = "provider_defined_exists"



class ActionExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class ActionResult:
    action_type: str = ""
    thread_id: str = ""
    status: "ActionExecutionStatus" = None
    message: str = ""

class RepairStatus(Enum):
    CREATED = "created"
    BACKING_UP = "backing_up"
    BACKED_UP = "backed_up"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RepairContext:
    codex_path: str
    backup_scope: list[str] = field(default_factory=list)


@dataclass
class RepairAction:
    issue_type: IssueType
    action_type: str
    target_files: list[str] = field(default_factory=list)
    thread_id: str = ""
    provider: str = ""
    risk_level: str = ""          # low | medium | high | manual
    requires_confirmation: bool = False
    preconditions: list[Precondition] = field(default_factory=list)
    description: str = ""
    detail: str = ""


@dataclass
class BackupFile:
    """单个备份文件的映射。"""
    original_path: str            # 原始文件完整路径
    backup_path: str              # 备份副本路径（相对于 snapshot.path）
    checksum: str = ""; size: int = 0            # SHA256 校验和


@dataclass
class BackupSnapshot:
    """一次完整备份的快照。包含 manifest 和所有文件映射。"""
    path: str = ""                # 备份目录路径
    created_at: str = ""          # ISO 8601
    source: str = ""              # 原始 .codex 路径
    manifest_path: str = ""       # manifest.json 路径
    files: list[BackupFile] = field(default_factory=list)
    verified: bool = False        # 备份后是否已通过校验


@dataclass
class RepairPlan:
    actions: list[RepairAction] = field(default_factory=list)
    total: int = 0
    auto_count: int = 0
    manual_count: int = 0
    requires_backup: bool = False
    can_rollback: bool = True
    summary: str = ""
    snapshot: BackupSnapshot | None = None; action_results: list['ActionResult'] = field(default_factory=list)
    status: RepairStatus = RepairStatus.CREATED


@dataclass
class RepairExecutionResult:
    """单次修复执行的结果。与 RepairPlan 分离，不修改 Plan 状态。"""
    status: 'RepairStatus' = None
    snapshot: BackupSnapshot | None = None; action_results: list['ActionResult'] = field(default_factory=list)
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    failed_actions: list[str] = field(default_factory=list)
    summary: str = ""
