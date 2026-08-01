"""CLI: python -m src scan|diagnose|plan|repair|gui [codex_home]"""

import argparse, os, sys, json
from dataclasses import asdict

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".codex")


def main():
    ap = argparse.ArgumentParser(description="Codex Repair Tool")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("scan", help="Scan Codex data")
    p.add_argument("codex_home", nargs="?", default=DEFAULT_PATH)

    p = sp.add_parser("diagnose", help="Diagnose issues")
    p.add_argument("codex_home", nargs="?", default=DEFAULT_PATH)
    p.add_argument("--json", action="store_true")

    p = sp.add_parser("plan", help="Generate repair plan")
    p.add_argument("codex_home", nargs="?", default=DEFAULT_PATH)

    p = sp.add_parser("repair", help="Execute repair")
    p.add_argument("codex_home", nargs="?", default=DEFAULT_PATH)
    p.add_argument("--yes", "-y", action="store_true")

    p = sp.add_parser("fix-auth", help="Restore ChatGPT account login (remove forced API auth keys, with confirmation)")
    p.add_argument("codex_home", nargs="?", default=DEFAULT_PATH)

    sp.add_parser("gui", help="Launch GUI")

    args = ap.parse_args()

    if args.cmd == "gui":
        from src.interfaces import launch_gui
        launch_gui()
        return

    handlers = {
        "scan": _cmd_scan,
        "diagnose": _cmd_diagnose,
        "plan": _cmd_plan,
        "repair": _cmd_repair,
        "fix-auth": _cmd_fix_auth,
    }
    handlers[args.cmd](args)


def _get_service(args):
    from src.application import RepairService, RepairOptions
    return RepairService(args.codex_home, RepairOptions(auto_confirm=getattr(args, "yes", False)))


def _cmd_scan(args):
    from src.scanner import compute_stats
    r = _get_service(args).scan()
    s = compute_stats(r)
    print("Provider: %s  Model: %s" % (r.current_provider or "-", r.current_model or "-"))
    print("Threads: %d active, %d archived" % (s.active_count, s.archived_count))
    print("Sessions: %d scanned, %s" % (r.jsonl_files_scanned, s.memory_label))


def _cmd_diagnose(args):
    d = _get_service(args).diagnose()
    if args.json:
        print(json.dumps({"version": d.version, "summary": asdict(d.summary),
                          "issues": [{"type": i.type.value, "severity": i.severity.value,
                                      "thread_id": i.thread_id, "provider": i.provider,
                                      "summary": i.summary, "repair_hint": i.repair_hint}
                                     for i in d.issues]}, indent=2, ensure_ascii=False))
        return
    s = d.summary
    print("=== Diagnosis ===")
    print("Issues: %d (HIGH=%d, MEDIUM=%d, LOW=%d), Blocking: %s" %
          (s.total, s.high, s.medium, s.low, "YES" if s.has_blocking_issue else "no"))
    for i in d.issues:
        print("  [%s] %s" % (i.severity.value.upper(), i.summary))


def _cmd_plan(args):
    svc = _get_service(args)
    p = svc.plan()
    print("=== Repair Plan ===")
    print("Actions: %d (auto=%d, confirm=%d)" % (p.total, p.auto_count, p.manual_count))
    if not p.actions: print("No actions."); return
    for i, a in enumerate(p.actions):
        f = "[auto]" if not a.requires_confirmation else "[confirm]"
        print("%d. %s %s  risk=%s" % (i + 1, f, a.description, a.risk_level))


def _cmd_repair(args):
    svc = _get_service(args)
    diag = svc.diagnose()
    plan = svc.plan(diag)
    if not plan.actions: print("No actions."); return

    print("%d actions (%d auto, %d confirm)" % (plan.total, plan.auto_count, plan.manual_count))
    if not args.yes and plan.manual_count > 0:
        r = input("Proceed? [y/N] ")
        if r.lower() not in ("y", "yes"): print("Aborted."); return

    print("Backing up...")
    result = svc.execute(plan)
    print("Done: %d ok, %d failed, %d skipped" % (result.success_count, result.failed_count, result.skipped_count))


def _cmd_fix_auth(args):
    """修复认证模式冲突：确认后移除强制 API 登录的配置键。

    默认绝不自动修改：只有用户输入 y/yes 确认后才执行。
    执行前先备份 config.toml（RepairService.execute 负责），
    修改为原子替换，且可通过备份回滚。
    """
    from src.repair.models import RepairPlan, RepairStatus
    svc = _get_service(args)
    diag = svc.diagnose()
    plan = svc.plan(diag)

    actions = [a for a in plan.actions if a.action_type == "restore_account_auth"]
    if not actions:
        print("未发现认证模式冲突：没有需要恢复的强制 API 登录配置。")
        return

    for a in actions:
        print("  [%s] %s" % (a.risk_level.upper(), a.description))
        if a.detail:
            print("      %s" % a.detail)

    r = input("确认恢复 ChatGPT 账号登录（会备份并修改 config.toml）？[y/N] ")
    if r.lower() not in ("y", "yes"):
        print("已取消，未修改任何文件。")
        return

    for a in actions:
        a.requires_confirmation = False
    sub = RepairPlan(
        actions=actions,
        total=len(actions),
        auto_count=len(actions),
        manual_count=0,
        requires_backup=True,
        can_rollback=True,
        status=RepairStatus.CREATED,
    )
    result = svc.execute(sub)
    print("Done: %d ok, %d failed, %d skipped" % (
        result.success_count, result.failed_count, result.skipped_count))
    if result.snapshot:
        print("备份位置: %s" % result.snapshot.path)


if __name__ == "__main__":
    main()
