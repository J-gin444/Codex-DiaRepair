"""RepairPlanner: 将 DiagnosisResult 映射为 RepairPlan。纯逻辑，不访问文件系统或数据库。"""

from ..diagnosis.models import DiagnosisResult, IssueType
from .models import (
    RepairAction, RepairPlan, RepairContext,
    Precondition, RepairStatus,
)

# Action 优先级（用于排序）
_PRIORITY = {
    "restore_account_auth": 0,
    "remove_orphan_index": 0,
    "normalize_path": 1,
    "add_provider_alias": 2,
    "cleanup_invalid_thread": 3,
    "manual": 4,
}


def plan(diagnosis: DiagnosisResult, context: RepairContext) -> RepairPlan:
    """从 DiagnosisResult + RepairContext 生成 RepairPlan。

    每条 Issue 映射为一个或多个 RepairAction。
    不接收 ScanResult。
    """
    actions: list[RepairAction] = []

    for issue in diagnosis.issues:
        mapped = _map_issue(issue)
        if mapped:
            actions.extend(mapped)

    # 按优先级排序
    actions.sort(key=lambda a: _PRIORITY.get(a.action_type, 99))

    auto = sum(1 for a in actions if not a.requires_confirmation)
    manual = sum(1 for a in actions if a.requires_confirmation)

    return RepairPlan(
        actions=actions,
        total=len(actions),
        auto_count=auto,
        manual_count=manual,
        requires_backup=len(actions) > 0,
        can_rollback=True,
        status=RepairStatus.CREATED,
    )


def _map_issue(issue) -> list[RepairAction]:
    """单条 Issue 映射为 RepairAction 列表。"""
    mapper = {
        IssueType.MISSING_PROVIDER_CONFIG: _map_missing_provider,
        IssueType.SESSION_INDEX_ORPHAN: _map_orphan_index,
        IssueType.INVALID_SESSION_PATH: _map_invalid_path,
        IssueType.MISSING_SESSION_FILE: _map_missing_file,
        IssueType.CURRENT_PROVIDER_UNDEFINED: _map_provider_undefined,
        IssueType.AUTH_FORCED_API: _map_auth_forced_api,
    }
    fn = mapper.get(issue.type)
    if fn:
        return fn(issue)
    return []


def _map_missing_provider(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.MISSING_PROVIDER_CONFIG,
        action_type="add_provider_alias",
        target_files=["config.toml"],
        provider=issue.provider,
        risk_level="manual",
        requires_confirmation=True,
        preconditions=[Precondition.CONFIG_EXISTS, Precondition.PROVIDER_DEFINED_EXISTS],
        description="Add provider alias for '%s'" % issue.provider,
        detail="Requires user to select a source provider to copy configuration from.",
    )]


def _map_orphan_index(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.SESSION_INDEX_ORPHAN,
        action_type="remove_orphan_index",
        target_files=["session_index.jsonl"],
        risk_level="low",
        requires_confirmation=False,
        preconditions=[],
        description="Remove orphan entries from session_index.jsonl",
    )]


def _map_invalid_path(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.INVALID_SESSION_PATH,
        action_type="normalize_path",
        target_files=["state_5.sqlite"],
        thread_id=issue.thread_id,
        risk_level="medium",
        requires_confirmation=False,
        preconditions=[Precondition.THREAD_EXISTS, Precondition.PATH_HAS_PREFIX],
        description="Normalize rollout_path for thread %s" % issue.thread_id,
    )]


def _map_missing_file(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.MISSING_SESSION_FILE,
        action_type="cleanup_invalid_thread",
        target_files=["state_5.sqlite", "goals_1.sqlite", "session_index.jsonl"],
        thread_id=issue.thread_id,
        risk_level="high",
        requires_confirmation=True,
        preconditions=[Precondition.THREAD_EXISTS, Precondition.SESSION_FILE_MISSING],
        description="Clean up invalid thread reference: %s" % issue.thread_id,
        detail="Thread references a nonexistent session file. "
               "Operation removes the database reference (conversation content already lost).",
    )]


def _map_provider_undefined(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.CURRENT_PROVIDER_UNDEFINED,
        action_type="manual",
        target_files=["config.toml"],
        provider=issue.provider,
        risk_level="manual",
        requires_confirmation=True,
        preconditions=[],
        description="Provider '%s' has no config section. Manual fix required." % issue.provider,
    )]


def _map_auth_forced_api(issue) -> list[RepairAction]:
    return [RepairAction(
        issue_type=IssueType.AUTH_FORCED_API,
        action_type="restore_account_auth",
        target_files=["config.toml"],
        risk_level="medium",
        requires_confirmation=True,
        preconditions=[Precondition.CONFIG_EXISTS],
        description="Restore ChatGPT account login (remove forced API auth keys)",
        detail="Removes forced_login_method / preferred_auth_method from config.toml "
               "so cloud sync works again. Requires confirmation; config is backed up "
               "before the change and can be rolled back.",
    )]
