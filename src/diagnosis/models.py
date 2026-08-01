"""Diagnosis 模块的数据模型。"""

from dataclasses import dataclass, field
from enum import Enum

DIAGNOSIS_RESULT_VERSION = "1.0"


class IssueType(Enum):
    MISSING_PROVIDER_CONFIG = "missing_provider_config"
    MISSING_SESSION_FILE = "missing_session_file"
    INVALID_SESSION_PATH = "invalid_session_path"
    SESSION_INDEX_ORPHAN = "session_index_orphan"
    CURRENT_PROVIDER_UNDEFINED = "current_provider_undefined"
    AUTH_FORCED_API = "auth_forced_api"


class Severity(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Issue:
    type: IssueType
    severity: Severity
    thread_id: str = ""
    provider: str = ""
    summary: str = ""
    detail: str = ""
    repair_hint: str = ""


@dataclass
class DiagnosisSummary:
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0
    total: int = 0
    has_blocking_issue: bool = False


@dataclass
class DiagnosisResult:
    version: str = DIAGNOSIS_RESULT_VERSION
    issues: list[Issue] = field(default_factory=list)
    summary: DiagnosisSummary = field(default_factory=DiagnosisSummary)
