"""Diagnosis 引擎: 输入 ScanResult，输出 DiagnosisResult。"""

import os
from .models import Issue, IssueType, Severity, DiagnosisResult, DiagnosisSummary


def diagnose(scan_result) -> DiagnosisResult:
    issues = []
    issues.extend(_check_missing_provider_config(scan_result))
    issues.extend(_check_missing_session_file(scan_result))
    issues.extend(_check_session_index_orphan(scan_result))
    issues.extend(_check_current_provider_undefined(scan_result))
    issues.extend(_check_auth_mode(scan_result))

    summary = DiagnosisSummary()
    summary.total = len(issues)
    for i in issues:
        if i.severity == Severity.HIGH:
            summary.high += 1
        elif i.severity == Severity.MEDIUM:
            summary.medium += 1
        elif i.severity == Severity.LOW:
            summary.low += 1
        else:
            summary.info += 1
    summary.has_blocking_issue = summary.high > 0

    return DiagnosisResult(issues=issues, summary=summary)


# 内置 Provider — Codex 内部使用的标识，不需要在 config.toml 中定义。
BUILTIN_PROVIDERS = {"codex_local_access"}

def _check_missing_provider_config(scan_result) -> list[Issue]:
    issues = []
    defined = set(scan_result.defined_providers.keys())
    for provider_name, count in scan_result.db_provider_distribution.items():
        if not provider_name or provider_name in defined or provider_name in BUILTIN_PROVIDERS:
            continue
        affected = [t.id for t in scan_result.thread_list if t.provider == provider_name][:10]
        detail = "Affected threads (%d total): %s" % (count, ", ".join(affected))
        if count > 10:
            detail += " ... and %d more" % (count - 10)
        issues.append(Issue(
            type=IssueType.MISSING_PROVIDER_CONFIG,
            severity=Severity.HIGH,
            provider=provider_name,
            summary="Provider '%s' used by %d threads is not defined in config.toml" % (provider_name, count),
            detail=detail,
            repair_hint="requires provider mapping",
        ))
    return issues


def _check_missing_session_file(scan_result) -> list[Issue]:
    issues = []
    for t in scan_result.thread_list:
        if not t.normalized_path:
            continue
        if not os.path.isfile(t.normalized_path):
            issues.append(Issue(
                type=IssueType.MISSING_SESSION_FILE,
                severity=Severity.HIGH,
                thread_id=t.id,
                summary="Session file not found: %s" % t.normalized_path,
                detail="File no longer exists on disk.",
                repair_hint="file no longer exists, cannot be recovered",
            ))
    return issues


def _check_session_index_orphan(scan_result) -> list[Issue]:
    thread_ids = {t.id for t in scan_result.thread_list}
    orphans = [e for e in scan_result.session_index_entries if e.id not in thread_ids]
    if not orphans:
        return []
    detail = "Orphan IDs: %s" % ", ".join(e.id for e in orphans[:10])
    if len(orphans) > 10:
        detail += " ... and %d more" % (len(orphans) - 10)
    return [Issue(
        type=IssueType.SESSION_INDEX_ORPHAN,
        severity=Severity.LOW,
        summary="%d session_index entries have no matching thread" % len(orphans),
        detail=detail,
        repair_hint="remove orphan entries from session_index.jsonl",
    )]


def _check_current_provider_undefined(scan_result) -> list[Issue]:
    p = scan_result.current_provider
    if not p or p in scan_result.defined_providers:
        return []
    return [Issue(
        type=IssueType.CURRENT_PROVIDER_UNDEFINED,
        severity=Severity.HIGH,
        provider=p,
        summary="Current provider '%s' is not defined in [model_providers]" % p,
        detail="config.toml has no [model_providers.%s] section." % p,
        repair_hint="requires user to fix config.toml manually",
    )]


def _check_auth_mode(scan_result) -> list[Issue]:
    """检查认证配置是否与缓存的登录状态冲突。

    只处理"配置强制 API 登录、但本地缓存的是 ChatGPT 账号登录"这一冲突：
    此时应用不会把对话同步到云端，属于认证模式导致的同步失效，
    与本地对话数据是否损坏无关。
    """
    auth = getattr(scan_result, "auth", None)
    if auth is None:
        return []

    forced_api = (
        auth.forced_login_method == "api"
        or auth.preferred_auth_method == "apikey"
    )
    if not forced_api:
        return []
    if auth.cached_auth_mode and auth.cached_auth_mode != "chatgpt":
        return []  # 用户主动选择 API 登录，不视为问题

    keys = []
    if auth.forced_login_method == "api":
        keys.append('forced_login_method = "api"')
    if auth.preferred_auth_method == "apikey":
        keys.append('preferred_auth_method = "apikey"')

    detail = (
        "config.toml 强制 API 登录（%s），但本地缓存的是 ChatGPT 账号登录"
        "（auth_mode=%s）。API 登录下应用不会把对话同步到云端；"
        "本地对话数据未损坏。" % ("、".join(keys), auth.cached_auth_mode or "未知")
    )
    return [Issue(
        type=IssueType.AUTH_FORCED_API,
        severity=Severity.MEDIUM,
        summary="认证配置强制 API 登录，云同步/账号功能不可用（本地对话数据未损坏）",
        detail=detail,
        repair_hint="确认后移除 forced_login_method / preferred_auth_method 两行并重启 Codex",
    )]
