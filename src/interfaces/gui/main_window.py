"""Codex Repair Tool - GUI"""

import os, sys, threading, tkinter as tk, tkinter.ttk as ttk
from datetime import datetime
from tkinter import filedialog as fd, messagebox as mb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from src.application import SessionService, ProviderService, TrashService, ExportService, ImportService
from src.application import RepairService, DeleteService, BackupService, Logger, RepairOptions
from src.application import VisibilityService
from src.application.options import default_backup_root, BackupConfig
from src.application.settings import load_settings, save_settings

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".codex")
TITLE = "Codex Repair Tool"


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("1100x820")
        self.minsize(900, 640)

        self._session = None
        self._repair = None
        self._scan_result = None
        self._diagnosis = None
        self._checked = set()
        self._logger = Logger()
        self._backup_root = load_settings().get("backup_root") or default_backup_root()
        self.backup_root_var = tk.StringVar(value=self._backup_root)

        self.count_var = tk.StringVar(value="--")
        self.memory_var = tk.StringVar(value="--")
        self.diag_summary_var = tk.StringVar(value="点击刷新诊断")
        self.repair_status_var = tk.StringVar(value="")
        self.provider_info_var = tk.StringVar(value="未扫描")
        self.sync_status_var = tk.StringVar(value="")
        self.cfg_provider_var = tk.StringVar(value="-")
        self.cfg_url_var = tk.StringVar(value="-")
        self.cfg_model_var = tk.StringVar(value="-")
        self.backup_status_var = tk.StringVar(value="未扫描")
        self.backup_path_var = tk.StringVar(value="")

        self._logger.on_message(self._on_log)
        self._build_config_bar()
        self._build_toolbar()
        self._build_notebook()
        self._build_log_panel()
        self._build_statusbar()
        self.after(200, self._auto_scan)

    # ================ config bar ================
    def _build_config_bar(self):
        cfg = ttk.LabelFrame(self, text="当前配置", padding=(10, 4, 10, 6))
        cfg.pack(fill=tk.X, padx=10, pady=(4, 2))
        row = ttk.Frame(cfg)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Provider").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row, textvariable=self.cfg_provider_var, state="readonly", width=14).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(row, text="Base URL").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row, textvariable=self.cfg_url_var, state="readonly", width=48).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(row, text="Model").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(row, textvariable=self.cfg_model_var, state="readonly", width=18).pack(side=tk.LEFT)

    # ================ toolbar ================
    def _build_toolbar(self):
        top = ttk.Frame(self, padding=(10, 2, 10, 4))
        top.pack(fill=tk.X)
        top.columnconfigure(1, weight=1)
        self.path_var = tk.StringVar(value=DEFAULT_PATH)
        ttk.Label(top, text="Codex 目录").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(top, textvariable=self.path_var).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(top, text="选择", command=self._choose_path).grid(row=0, column=2, padx=(0, 4))
        ttk.Button(top, text="扫描", command=self._safe_scan).grid(row=0, column=3, padx=(0, 4))
        ttk.Button(top, text="同步", command=self._safe_sync).grid(row=0, column=4, padx=(0, 6))
        ttk.Label(top, textvariable=self.sync_status_var, foreground="gray").grid(row=0, column=5, sticky="w")

    def _choose_path(self):
        path = fd.askdirectory(initialdir=self.path_var.get())
        if path:
            self.path_var.set(path)
            self._safe_scan()

    # ================ notebook ================
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self, padding=(10, 4, 10, 10))
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self._tab_names = ["对话管理", "废纸篓", "备份与恢复", "诊断与修复"]
        for name, builder in [("对话管理", self._build_thread_tab), ("废纸篓", self._build_trash_tab),
                               ("备份与恢复", self._build_backup_tab), ("诊断与修复", self._build_repair_tab)]:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=name)
            builder(frame)
        self._backup_tab_index = self._tab_names.index("备份与恢复")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)


    # ================ tab 1: threads ================
    def _build_thread_tab(self, parent):
        f = ttk.Frame(parent, padding=10); f.pack(fill=tk.BOTH, expand=True)
        fb = ttk.Frame(f); fb.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(fb, text="项目").pack(side=tk.LEFT, padx=(0, 4))
        self.project_var = tk.StringVar(value="全部")
        self.project_cb = ttk.Combobox(fb, textvariable=self.project_var, state="readonly", width=30)
        self.project_cb.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(fb, text="Provider").pack(side=tk.LEFT, padx=(0, 4))
        self.prov_filter_var = tk.StringVar(value="全部")
        self.prov_filter_cb = ttk.Combobox(fb, textvariable=self.prov_filter_var, state="readonly", width=16)
        self.prov_filter_cb.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(fb, text="筛选", command=self._apply_filter).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(fb, text="清除", command=self._clear_filter).pack(side=tk.LEFT)
        ttk.Label(fb, textvariable=self.count_var).pack(side=tk.LEFT, padx=(20, 12))
        ttk.Label(fb, textvariable=self.memory_var).pack(side=tk.LEFT)

        tb = ttk.Frame(f); tb.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(tb, text="全选", command=self._toggle_select_all).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tb, text="取消", command=self._clear_selection).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(tb, text="移入废纸篓", command=self._move_to_trash).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(tb, text="彻底删除", command=self._permanent_delete).pack(side=tk.LEFT)
        ttk.Label(tb, text="  废纸篓可恢复，彻底删除不可恢复  ", foreground="gray").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(tb, text="导出选中", command=self._export_selected).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(tb, text="导入", command=self._import_threads).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(tb, text="修复对话可见度", command=self._fix_visibility).pack(side=tk.RIGHT, padx=(4, 0))

        ttk.Label(f, text="切换 provider/路由后侧栏看不到历史对话时，点「修复对话可见度」一键对齐；"
                          "修复前需先完全退出 Codex，操作前会自动备份。",
                  foreground="gray", anchor="w").pack(fill=tk.X, pady=(0, 8))

        nb = ttk.Notebook(f); nb.pack(fill=tk.BOTH, expand=True)
        cols = ("checked", "title", "provider", "size", "updated", "id")
        for tab_name, attr in [("聊天窗口", "active_tree"), ("归档对话", "archived_tree")]:
            frame = ttk.Frame(nb)
            tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
            tree.heading("checked", text=""); tree.heading("title", text="标题"); tree.heading("provider", text="Provider")
            tree.heading("size", text="大小"); tree.heading("updated", text="更新时间"); tree.heading("id", text="Thread ID")
            tree.column("checked", width=30, anchor="center", stretch=False); tree.column("title", width=320, anchor="w")
            tree.column("provider", width=80, anchor="center", stretch=False); tree.column("size", width=80, anchor="e", stretch=False)
            tree.column("updated", width=120, anchor="center", stretch=False); tree.column("id", width=200, anchor="w")
            sc = ttk.Scrollbar(frame, command=tree.yview); tree.configure(yscrollcommand=sc.set)
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sc.pack(side=tk.RIGHT, fill=tk.Y)
            tree.bind("<Button-1>", lambda e, t=tree: self._on_click(e, t))
            setattr(self, attr, tree); nb.add(frame, text=tab_name)

    # ================ tab 2: trash ================
    def _build_trash_tab(self, parent):
        f = ttk.Frame(parent, padding=10); f.pack(fill=tk.BOTH, expand=True)
        tb = ttk.Frame(f); tb.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(tb, text="废纸篓中的对话可以恢复。清空后永久删除。", foreground="gray").pack(side=tk.LEFT)
        ttk.Button(tb, text="刷新", command=self._refresh_trash).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(tb, text="清空废纸篓", command=self._empty_trash).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(tb, text="恢复选中", command=self._restore_from_trash).pack(side=tk.RIGHT)
        cols = ("title", "provider", "deleted_at", "id")
        self.trash_tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="extended")
        self.trash_tree.heading("title", text="标题"); self.trash_tree.heading("provider", text="Provider")
        self.trash_tree.heading("deleted_at", text="删除时间"); self.trash_tree.heading("id", text="Thread ID")
        self.trash_tree.column("title", width=320); self.trash_tree.column("provider", width=100, anchor="center")
        self.trash_tree.column("deleted_at", width=180, anchor="center"); self.trash_tree.column("id", width=250, anchor="w")
        sc = ttk.Scrollbar(f, command=self.trash_tree.yview); self.trash_tree.configure(yscrollcommand=sc.set)
        self.trash_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sc.pack(side=tk.RIGHT, fill=tk.Y)

    # ================ tab 3: backup ================
    def _build_backup_tab(self, parent):
        f = ttk.Frame(parent, padding=10); f.pack(fill=tk.BOTH, expand=True)
        root_row = ttk.Frame(f); root_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(root_row, text="备份根目录").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(root_row, textvariable=self.backup_root_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(root_row, text="选择", command=self._choose_backup_root).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(root_row, text="应用", command=self._apply_backup_root).pack(side=tk.LEFT)
        ttk.Label(f, text="完整备份含会话文件；修复流程自动备份仅含核心数据（数据库/索引/配置），"
                          "列表「包含内容」列会标明；双击列表项可查看备份内容。",
                  foreground="gray").pack(fill=tk.X, pady=(0, 6))
        top = ttk.LabelFrame(f, text="当前状态", padding=6); top.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(top, textvariable=self.backup_status_var).pack(anchor="w")
        ttk.Button(top, text="立即备份", command=self._do_backup).pack(anchor="w", pady=(4, 0))
        hist = ttk.LabelFrame(f, text="历史备份", padding=6); hist.pack(fill=tk.BOTH, expand=True)
        tb = ttk.Frame(hist); tb.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(tb, text="刷新", command=self._refresh_backups).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text="恢复选中", command=self._restore_backup).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text="验证", command=self._validate_backup).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(tb, text="删除备份", command=self._delete_backup).pack(side=tk.LEFT)

        # 备份路径显示（只读，可选中复制）
        path_row = ttk.Frame(hist)
        path_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(path_row, text="备份路径").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Entry(path_row, textvariable=self.backup_path_var, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(path_row, text="复制", command=self._copy_backup_path).pack(side=tk.LEFT)
        cols = ("created", "source", "content", "files", "size", "ok")
        self.backup_tree = ttk.Treeview(hist, columns=cols, show="headings", selectmode="browse", height=6)
        self.backup_tree.heading("created", text="创建时间"); self.backup_tree.heading("source", text="来源")
        self.backup_tree.heading("content", text="包含内容"); self.backup_tree.heading("files", text="文件数")
        self.backup_tree.heading("size", text="大小"); self.backup_tree.heading("ok", text="校验")
        self.backup_tree.column("created", width=160, anchor="center"); self.backup_tree.column("source", width=180, anchor="w")
        self.backup_tree.column("content", width=110, anchor="center"); self.backup_tree.column("files", width=60, anchor="center")
        self.backup_tree.column("size", width=80, anchor="e")
        self.backup_tree.column("ok", width=50, anchor="center")
        sc = ttk.Scrollbar(hist, command=self.backup_tree.yview); self.backup_tree.configure(yscrollcommand=sc.set)
        self.backup_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sc.pack(side=tk.RIGHT, fill=tk.Y)
        self.backup_tree.bind("<<TreeviewSelect>>", self._on_backup_tree_select)
        self.backup_tree.bind("<Double-1>", self._on_backup_double_click)

    # ================ tab 4: repair ================
    def _build_repair_tab(self, parent):
        f = ttk.Frame(parent, padding=10); f.pack(fill=tk.BOTH, expand=True)
        pf = ttk.LabelFrame(f, text="Provider 信息", padding=6); pf.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(pf, textvariable=self.provider_info_var).pack(anchor="w")
        df = ttk.LabelFrame(f, text="诊断结果", padding=6); df.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(df, textvariable=self.diag_summary_var).pack(anchor="w")
        bf = ttk.Frame(f); bf.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(bf, text="刷新诊断", command=self._refresh_diag).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bf, text="执行修复", command=self._do_repair).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(bf, textvariable=self.repair_status_var).pack(side=tk.LEFT, padx=(12, 0))
        cols = ("severity", "type", "summary", "hint")
        self.issue_tree = ttk.Treeview(f, columns=cols, show="headings", height=6)
        for h, w in [("级别", 60), ("类型", 150), ("描述", 380), ("修复方向", 180)]:
            ii = ["级别","类型","描述","修复方向"].index(h)
            self.issue_tree.heading(cols[ii], text=h); self.issue_tree.column(cols[ii], width=w, anchor="w")
        sc = ttk.Scrollbar(f, command=self.issue_tree.yview); self.issue_tree.configure(yscrollcommand=sc.set)
        self.issue_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sc.pack(side=tk.RIGHT, fill=tk.Y)

    # ================ log panel ================
    def _build_log_panel(self):
        self.log_frame = ttk.LabelFrame(self, text="日志", padding=(10, 2, 10, 4))
        self.log_text = tk.Text(self.log_frame, height=5, wrap=tk.WORD, font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_log(self, line):
        if hasattr(self, "log_text"):
            self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)

    def _toggle_log(self):
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
            self._log_btn.configure(text="显示日志")
        else:
            self.log_frame.pack(fill=tk.X, padx=10, pady=(0, 4), after=self.notebook)
            self._log_btn.configure(text="隐藏日志")

    # ================ status bar ================
    def _build_statusbar(self):
        bar = ttk.Frame(self, padding=(10, 0, 10, 6)); bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(bar, textvariable=self.status_var).pack(side=tk.LEFT)
        self._log_btn = ttk.Button(bar, text="显示日志", command=self._toggle_log)
        self._log_btn.pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Label(bar, text="60 tests  |  zero deps", foreground="gray").pack(side=tk.RIGHT)

    # ================ services ================
    def _init_services(self):
        p = os.path.abspath(os.path.expanduser(self.path_var.get()))
        trash_dir = os.path.join(self._backup_root, "trash")
        self._session = SessionService(p)
        self._repair = RepairService(
            p, RepairOptions(backup=BackupConfig(directory=self._backup_root)))
        self._trash = TrashService(trash_dir)
        self._delete = DeleteService(p, self._backup_root)
        self._backup = BackupService(p, self._backup_root)
        self._visibility = VisibilityService(p, self._backup_root)
        self._import_svc = ImportService(p)

    def _ensure_services(self):
        if self._session is None: self._init_services()

    # ================ async ================
    def _run_async(self, label, fn, on_done=None):
        self.status_var.set(label); self._logger.log(label)
        def t():
            try: r = fn(); self.after(0, lambda: self._on_done(r, on_done))
            except Exception as e: self.after(0, lambda: self._on_error(str(e)))
        threading.Thread(target=t, daemon=True).start()

    def _on_done(self, r, cb):
        self.status_var.set("\u5b8c\u6210")
        if cb:
            cb(r)

    def _on_error(self, m):
        self.status_var.set("\u5931\u8d25")
        self._logger.log("ERROR: " + m)
        mb.showerror(TITLE, m)

    # ================ scan / sync ================
    def _auto_scan(self):
        if os.path.isdir(self.path_var.get()): self._safe_scan()

    def _safe_scan(self):
        self._init_services()
        self._run_async("扫描中...", lambda: self._session.scan(), self._on_scan_done)

    def _safe_sync(self):
        self._ensure_services()
        self._run_async("同步中...", lambda: self._session.sync(), self._on_sync_done)

    def _on_scan_done(self, r):
        self._scan_result = r
        m = "扫描完成: %d threads" % len(r.thread_list)
        self.status_var.set(m); self._logger.log(m)
        self._update_filters(); self._render_threads(); self._update_provider_info(); self._update_config_display()
        self.backup_status_var.set("Threads: %d  |  文件: 未备份" % len(r.thread_list))

    def _on_sync_done(self, s):
        m = "同步: 新增%d 更新%d 删除%d" % (s.added, s.updated, s.removed)
        self.sync_status_var.set(m); self._logger.log(m)
        self._safe_scan()

    def _update_filters(self):
        r = self._scan_result
        if not r: return
        d = r.diagnostics; projects = d.project_cwds if hasattr(d, "project_cwds") else ["Unknown"]
        self.project_cb["values"] = ["全部"] + [_strip_win_prefix(p) for p in projects]
        providers = sorted({t.provider for t in r.thread_list if t.provider})
        self.prov_filter_cb["values"] = ["全部"] + providers

    def _update_provider_info(self):
        r = self._scan_result
        if not r: return
        provs = ProviderService.list_providers(r)
        lines = []
        for p in provs:
            lines.append("%s [%s] %s  threads: %d" % (p["name"], p["source"], p["base_url"], p["thread_count"]))
        self.provider_info_var.set("\\n".join(lines[:8]) if lines else "(none)")

    def _update_config_display(self):
        r = self._scan_result
        if not r: return
        provs = ProviderService.list_providers(r)
        cp = r.current_provider or ""
        for p in provs:
            if p["name"] == cp:
                self.cfg_provider_var.set(p["name"]); self.cfg_url_var.set(p["base_url"])
                self.cfg_model_var.set(r.current_model or p.get("model", "-")); return
        self.cfg_provider_var.set(cp or "-"); self.cfg_url_var.set("-"); self.cfg_model_var.set(r.current_model or "-")

    # ================ threads ================
    def _apply_filter(self): self._render_threads()
    def _clear_filter(self): self.project_var.set("全部"); self.prov_filter_var.set("全部"); self._render_threads()

    def _render_threads(self):
        r = self._scan_result
        if r is None: return
        for tree in [self.active_tree, self.archived_tree]: tree.delete(*tree.get_children())
        pf = self.project_var.get(); vf = self.prov_filter_var.get()
        total_size = 0; shown = 0
        for t in r.thread_list:
            if pf != "全部" and _strip_win_prefix(t.cwd) != pf: continue
            if vf != "全部" and t.provider != vf: continue
            total_size += t.size_bytes; shown += 1
            tree = self.archived_tree if t.archived else self.active_tree
            mark = "[X]" if t.id in self._checked else "[ ]"
            tree.insert("", "end", iid=t.id, values=(mark, t.title_short, t.provider, t.size_label, t.updated_label, t.id))
        self.count_var.set("%d / %d (%d archived)" % (shown, len(r.thread_list), len(r.archived_threads)))
        self.memory_var.set(_fmt_bytes(total_size))

    def _toggle_select_all(self):
        r = self._scan_result
        if r and len(self._checked) == len(r.thread_list): self._checked.clear()
        elif r: self._checked = {t.id for t in r.thread_list}
        self._render_threads()

    def _clear_selection(self): self._checked.clear(); self._render_threads()

    def _on_click(self, e, tree):
        if tree.identify_region(e.x, e.y) == "cell" and tree.identify_column(e.x) == "#1":
            iid = tree.identify_row(e.y)
            if iid:
                if iid in self._checked: self._checked.remove(iid)
                else: self._checked.add(iid)
                self._render_threads()

    # ================ export/import ================
    def _export_selected(self):
        if not self._checked:
            mb.showinfo(TITLE, "请先勾选要导出的对话。"); return
        out_dir = fd.askdirectory(title="选择导出目录")
        if not out_dir: return
        ids = list(self._checked)
        self._run_async("导出中...", lambda: ExportService.export_threads(ids, self._scan_result, out_dir), self._on_export_done)

    def _on_export_done(self, r):
        m = "导出完成: %d 个文件" % r.exported
        self.status_var.set(m); self._logger.log(m)
        if r.failed: self._logger.log("导出失败: %d 个" % r.failed)

    def _import_threads(self):
        in_dir = fd.askdirectory(title="选择包含 .json 文件的导入目录")
        if not in_dir: return
        if not mb.askyesno(TITLE, "将从 %s 导入对话。\n\n导入前会自动创建备份。\n已存在的 threadId 将跳过。\n是否继续？" % in_dir): return
        self._ensure_services()
        # 导入前先备份
        self._run_async("备份中...", lambda: self._backup.create_backup(), lambda info: self._do_import(in_dir))

    def _do_import(self, in_dir):
        self._run_async("导入中...", lambda: self._import_svc.import_threads(in_dir, overwrite=False), self._on_import_done)

    def _on_import_done(self, r):
        m = "导入: %s" % r.status
        self.status_var.set(m); self._logger.log(m)
        self._safe_scan()

    # ================ delete ================
    def _move_to_trash(self):
        if not self._checked: mb.showinfo(TITLE, "请先勾选。"); return
        ids = list(self._checked); n = len(ids)
        if not mb.askyesno(TITLE, "将 %d 个对话移入废纸篓。\n\n可恢复。是否继续？" % n): return
        self._ensure_services()
        self._run_async("移入废纸篓...", lambda: self._do_trash_move(ids), self._on_trash_done)

    def _do_trash_move(self, ids):
        self._trash.move_to_trash(ids, self._scan_result)
        return self._repair.delete_threads(ids)

    def _on_trash_done(self, r):
        sc = r.success_count if hasattr(r, 'success_count') else 0
        m = "已移入废纸篓: %d 个对话" % sc
        self._checked.clear(); self.status_var.set(m); self._logger.log(m)
        self._safe_scan(); self._refresh_trash()

    def _permanent_delete(self):
        if not self._checked: mb.showinfo(TITLE, "请先勾选。"); return
        ids = list(self._checked); n = len(ids)
        if not mb.askyesno(TITLE, "永久删除 %d 个对话。\n\n不可恢复！是否继续？" % n, icon="warning"): return
        self._ensure_services()
        self._run_async("彻底删除...", lambda: self._delete.permanent_delete(ids), self._on_perm_delete_done)

    def _on_perm_delete_done(self, r):
        m = "彻底删除完成: backup=%s" % r.backup_path if r.backup_path else "彻底删除完成"
        self._checked.clear(); self.status_var.set(m); self._logger.log(m); self._safe_scan()

    # ================ trash ================
    def _refresh_trash(self):
        self._ensure_services(); self.trash_tree.delete(*self.trash_tree.get_children())
        for e in self._trash.list_entries():
            self.trash_tree.insert("", "end", iid=e.id, values=(e.title, e.provider, _fmt_ts(e.deleted_at), e.id))

    def _on_tab_changed(self, event):
        """Tab switch: 各页点击时自动刷新对应列表。"""
        if not hasattr(self, "_backup"):
            return
        tab_index = event.widget.index(event.widget.select())
        if tab_index == 0:
            self._logger.log("[%s] 自动刷新对话列表" % datetime.now().strftime("%H:%M:%S"))
            self._safe_scan()
        elif tab_index == 1:
            self._logger.log("[%s] 自动刷新废纸篓" % datetime.now().strftime("%H:%M:%S"))
            self._refresh_trash()
        elif tab_index == self._backup_tab_index:
            self._logger.log("[%s] 自动刷新备份列表" % datetime.now().strftime("%H:%M:%S"))
            self._refresh_backups_async()
        elif tab_index == 3:
            self._logger.log("[%s] 自动刷新诊断" % datetime.now().strftime("%H:%M:%S"))
            self._refresh_diag()

    def _empty_trash(self):
        if not mb.askyesno(TITLE, "清空废纸篓？不可恢复。", icon="warning"): return
        self._ensure_services(); self._trash.empty_trash(); self._refresh_trash()

    def _restore_from_trash(self):
        sel = self.trash_tree.selection()
        if not sel: mb.showinfo(TITLE, "请先选择。"); return
        for iid in sel:
            if not self._trash.restore(iid, codex_path=self.path_var.get()): mb.showwarning(TITLE, "恢复失败: %s" % iid)
        self._refresh_trash(); self._safe_scan(); self._logger.log("恢复: %d 个对话" % len(sel))

    # ================ backup ================
    def _do_backup(self):
        self._ensure_services()
        self._run_async("备份中...", lambda: self._backup.create_backup(), self._on_backup_done)

    def _on_backup_done(self, info):
        self.backup_status_var.set("Threads: %d  |  大小: %s  |  校验: %s" %
            (info.threads, _fmt_bytes(info.size), "通过" if info.verified else "失败"))
        m = "备份完成: %s" % info.path; self.status_var.set(m); self._logger.log(m)
        self._refresh_backups()
        self.backup_path_var.set(info.path)
    def _on_backup_tree_select(self, event):
        sel = self.backup_tree.selection()
        if sel:
            self.backup_path_var.set(sel[0])
            self._logger.log("选中备份: %s" % sel[0])
            self._logger.log("选中备份: %s" % sel[0])

    def _choose_backup_root(self):
        d = fd.askdirectory(
            initialdir=self.backup_root_var.get() or default_backup_root(),
            title="选择备份根目录")
        if d:
            self.backup_root_var.set(os.path.abspath(d))

    def _apply_backup_root(self):
        d = self.backup_root_var.get().strip()
        if not d:
            mb.showwarning(TITLE, "请先填写备份根目录路径。")
            return
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            if not mb.askyesno(TITLE, "目录不存在：%s\n是否创建？" % d):
                return
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as e:
                mb.showerror(TITLE, "创建目录失败: %s" % e)
                return
        self._backup_root = d
        self.backup_root_var.set(d)
        save_settings({"backup_root": d})
        self._init_services()
        self._refresh_backups()
        self.backup_status_var.set("备份根目录已切换: %s" % d)
        self._logger.log("备份根目录已切换: %s" % d)

    def _copy_backup_path(self):
        path = self.backup_path_var.get()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(path)
        self._logger.log("已复制路径: %s" % path)

    def _refresh_backups(self):
        self._ensure_services(); self.backup_tree.delete(*self.backup_tree.get_children())
        for b in self._backup.list_backups():
            self.backup_tree.insert("", "end", iid=b.path, values=(
                _fmt_ts(b.created_at), b.source or "-", _backup_content_label(b),
                str(b.files), _fmt_bytes(b.size), "OK" if b.verified else "FAIL"))

    def _refresh_backups_async(self):
        """Async refresh backup list via _run_async to avoid blocking GUI."""
        self._run_async("自动刷新备份列表...", lambda: self._backup.list_backups(), self._on_auto_backup_refreshed)

    def _on_auto_backup_refreshed(self, backups):
        """Callback: populate backup tree from async result and write log."""
        self.backup_tree.delete(*self.backup_tree.get_children())
        count = 0
        for b in backups:
            self.backup_tree.insert("", "end", iid=b.path, values=(
                _fmt_ts(b.created_at), b.source or "-", _backup_content_label(b),
                str(b.files), _fmt_bytes(b.size), "OK" if b.verified else "FAIL"))
            count += 1
        self._logger.log("自动刷新备份列表完成: %d 个备份" % count)
        self.status_var.set("备份已刷新: %d 个备份" % count)

    def _restore_backup(self):
        sel = self.backup_tree.selection()
        if not sel: mb.showinfo(TITLE, "请先选择备份。"); return
        info = next((b for b in self._backup.list_backups() if b.path == sel[0]), None)
        if info is None: return
        if not info.verified: mb.showwarning(TITLE, "校验未通过。"); return
        if info.has_sessions:
            msg = "将用此备份覆盖当前数据（含 %d 个会话文件），恢复到备份时状态。继续？" % info.session_count
        else:
            msg = ("该备份仅含核心数据（数据库/索引/配置），不含会话文件。\n"
                   "恢复后会话文件保持现状，可能与索引不一致。继续？")
        if not mb.askyesno(TITLE, msg, icon="warning"): return
        self._ensure_services()
        self._run_async("恢复中...", lambda: self._backup.restore_full(sel[0]), self._on_restore_done)

    def _on_restore_done(self, r):
        m = "恢复完成: before=%d after=%d files=%d" % (r.before, r.after, len(r.restored_files))
        self.status_var.set(m); self._logger.log(m)
        self._safe_scan(); self._refresh_backups()

    def _validate_backup(self):
        sel = self.backup_tree.selection()
        if not sel: mb.showinfo(TITLE, "请先选择备份。"); return
        info = self._backup.validate_backup(sel[0])
        if info: mb.showinfo(TITLE, "校验: %s\n文件: %d\n大小: %s" % ("通过" if info.verified else "未通过", info.files, _fmt_bytes(info.size)))
        else: mb.showerror(TITLE, "无法读取。")
        self._refresh_backups()

    def _delete_backup(self):
        self._ensure_services()
        sel = self.backup_tree.selection()
        if not sel: mb.showinfo(TITLE, "请先选择备份。"); return
        path = sel[0]
        info = next((b for b in self._backup.list_backups() if b.path == path), None)
        if info is None: return
        if info.has_sessions:
            n = len(self._backup.get_backup_threads(path))
            detail = "完整备份，包含 %d 个对话项（含会话文件）。" % n
        else:
            n = len(self._backup.get_backup_files(path))
            detail = "仅核心数据备份（数据库/索引/配置，不含会话文件），共 %d 个文件。" % n
        msg = "确认删除备份 %s？\n%s\n删除后不可恢复。" % (_fmt_ts(info.created_at), detail)
        if not mb.askyesno(TITLE, msg, icon="warning"):
            return
        self._run_async(
            "删除备份...",
            lambda: self._backup.delete_backup(path),
            self._on_delete_backup_done,
        )

    def _on_backup_double_click(self, event):
        self._ensure_services()
        iid = self.backup_tree.identify_row(event.y)
        if not iid:
            return
        info = next((b for b in self._backup.list_backups() if b.path == iid), None)
        if info is None:
            return
        self._show_backup_preview(iid, info)

    def _show_backup_preview(self, path, info):
        """展示备份内容：完整备份显示对话项，核心备份显示文件清单。"""
        threads = self._backup.get_backup_threads(path) if info.has_sessions else []
        files = [] if info.has_sessions else self._backup.get_backup_files(path)
        dlg = tk.Toplevel(self)
        dlg.title("备份内容")
        dlg.geometry("680x440")
        dlg.transient(self)
        dlg.grab_set()
        if info.has_sessions:
            head = "备份 %s\n包含 %d 个对话项。" % (_fmt_ts(info.created_at), len(threads))
        else:
            head = "备份 %s\n该备份不包含会话文件（仅核心数据：数据库/索引/配置），包含 %d 个文件。" % (
                _fmt_ts(info.created_at), len(files))
        ttk.Label(dlg, text=head, wraplength=640, justify="left").pack(fill=tk.X, padx=10, pady=(10, 4))

        frame = ttk.Frame(dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        if info.has_sessions:
            cols = ("id", "title", "provider")
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
            labels = [("Thread", 190), ("标题", 340), ("Provider", 90)]
            for h, w in labels:
                ii = [x[0] for x in labels].index(h)
                tree.heading(cols[ii], text=h)
                tree.column(cols[ii], width=w, anchor="w")
        else:
            cols = ("file", "size")
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
            labels = [("文件", 460), ("大小", 90)]
            for h, w in labels:
                ii = [x[0] for x in labels].index(h)
                tree.heading(cols[ii], text=h)
                tree.column(cols[ii], width=w, anchor="w")
        vsb = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        if info.has_sessions:
            for t in threads[:500]:
                tree.insert("", "end", values=(
                    t.get("id", "") or "-",
                    (t.get("title") or "")[:60],
                    t.get("model_provider", "") or "-",
                ))
            if len(threads) > 500:
                tree.insert("", "end", values=("...", "还有 %d 项未显示" % (len(threads) - 500), ""))
        else:
            for f in files[:500]:
                tree.insert("", "end", values=(
                    f.get("path", "") or "-",
                    _fmt_bytes(f.get("size", 0)),
                ))
            if len(files) > 500:
                tree.insert("", "end", values=("...", "还有 %d 项未显示" % (len(files) - 500)))

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btns, text="关闭", command=dlg.destroy).pack(side=tk.RIGHT, padx=(4, 0))

    def _on_delete_backup_done(self, result):
        ok, err = result
        if ok:
            mb.showinfo(TITLE, "备份已删除。")
        else:
            mb.showerror(TITLE, "删除失败: %s" % err)
        self._refresh_backups()

    # ================ diagnosis ================
    def _refresh_diag(self):
        self._ensure_services(); self._run_async("诊断中...", self._repair.diagnose, self._on_diag_done)

    def _on_diag_done(self, d):
        self._diagnosis = d; s = d.summary
        self.diag_summary_var.set("%d issues (HIGH=%d, MEDIUM=%d, LOW=%d)  阻塞: %s" %
            (s.total, s.high, s.medium, s.low, "是" if s.has_blocking_issue else "否"))
        self.issue_tree.delete(*self.issue_tree.get_children())
        for i in d.issues:
            self.issue_tree.insert("", "end", values=(i.severity.value.upper(), i.type.value, i.summary, i.repair_hint))

    def _do_repair(self):
        if self._diagnosis is None: mb.showinfo(TITLE, "请先刷新诊断。"); return
        plan = self._repair.plan(self._diagnosis)
        if not plan.actions: mb.showinfo(TITLE, "没有需要修复的内容。"); return
        if not mb.askyesno(TITLE, "执行 %d 个修复操作？" % plan.total): return
        self._run_async("修复中...", lambda: self._repair.execute(plan), self._on_repair_done)

    def _on_repair_done(self, r):
        self.repair_status_var.set("%d ok, %d fail, %d skip" % (r.success_count, r.failed_count, r.skipped_count))
        self._refresh_diag()

    # ================ visibility repair (tab 1) ================
    def _fix_visibility(self):
        self._ensure_services()
        self._run_async("诊断对话可见性...", self._visibility.diagnose, self._on_visibility_diag)

    def _on_visibility_diag(self, report):
        self._visibility_report = report
        if not report.findings:
            mb.showinfo(TITLE, "未发现对话可见性问题。\n\n" + report.summary)
            return

        dlg = tk.Toplevel(self)
        dlg.title("对话可见度修复")
        dlg.geometry("880x480")
        dlg.transient(self)
        dlg.grab_set()

        ttk.Label(dlg, text=report.summary, wraplength=840, justify="left").pack(
            fill=tk.X, padx=10, pady=(10, 2))
        ttk.Label(dlg, text="执行前会自动完整备份，且要求先关闭 Codex；此操作会把历史会话的 provider 对齐到"
                            "当前 provider（应用侧栏同一时刻只显示当前 provider 的会话）；"
                            "云同步与侧栏可见性相互独立；高风险整库恢复默认不勾选。",
                  foreground="gray", wraplength=840, justify="left").pack(fill=tk.X, padx=10, pady=(0, 4))

        frame = ttk.Frame(dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        cols = ("sel", "thread", "problem", "suggestion", "risk")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none", height=12)
        labels = [("选择", 44), ("Thread", 185), ("检测结果", 300), ("建议", 240), ("风险", 50)]
        for h, w in labels:
            ii = [x[0] for x in labels].index(h)
            tree.heading(cols[ii], text=h)
            tree.column(cols[ii], width=w, anchor="w")
        vsb = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._visibility_tree = tree
        self._visibility_findings = {}
        for f in report.findings:
            iid = tree.insert("", "end", values=(
                "[x]" if f.risk != "high" else "[ ]",
                f.thread_id or "-", f.summary, f.suggestion, f.risk))
            self._visibility_findings[iid] = f
        tree.bind("<Button-1>", self._on_visibility_toggle)

        btns = ttk.Frame(dlg)
        btns.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(btns, text="全部勾选", command=lambda: self._set_visibility_all(True)).pack(
            side=tk.LEFT, padx=(0, 4))
        ttk.Button(btns, text="只勾选低/中风险", command=self._set_visibility_safe).pack(
            side=tk.LEFT, padx=(0, 4))
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btns, text="确认修复", command=lambda: self._confirm_visibility(dlg)).pack(
            side=tk.RIGHT)

    def _on_visibility_toggle(self, event):
        iid = self._visibility_tree.identify_row(event.y)
        if not iid:
            return
        cur = self._visibility_tree.set(iid, "sel")
        self._visibility_tree.set(iid, "sel", "[ ]" if cur == "[x]" else "[x]")

    def _set_visibility_all(self, flag):
        for iid in self._visibility_tree.get_children():
            self._visibility_tree.set(iid, "sel", "[x]" if flag else "[ ]")

    def _set_visibility_safe(self):
        for iid in self._visibility_tree.get_children():
            f = self._visibility_findings[iid]
            self._visibility_tree.set(iid, "sel", "[x]" if f.risk != "high" else "[ ]")

    def _confirm_visibility(self, dlg):
        kinds = []
        for iid in self._visibility_tree.get_children():
            if self._visibility_tree.set(iid, "sel") == "[x]":
                kinds.append(self._visibility_findings[iid].kind)
        if not kinds:
            mb.showwarning(TITLE, "未选择任何修复项。")
            return
        dlg.destroy()
        report = self._visibility_report
        self._run_async(
            "执行可见度修复...",
            lambda: self._visibility.execute(report, kinds),
            self._on_visibility_done,
        )

    def _on_visibility_done(self, result):
        if not result.get("ok"):
            mb.showerror(TITLE, result.get("message", "修复失败"))
            return
        lines = [
            "数据库对话数: %d -> %d" % (result["before"], result["after"]),
            "备份位置: %s" % result["backup_path"],
            "",
            "执行明细:",
        ] + ["  " + a for a in result["applied"]]
        mb.showinfo(TITLE, "可见度修复完成\n\n" + "\n".join(lines))
        self._auto_scan()

def _fmt_bytes(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return "%d %s" % (n, u) if u == "B" else "%.1f %s" % (n, u)
        n /= 1024


def _strip_win_prefix(path):
    """去掉 Windows 扩展长路径前缀 \\\\?\\，用于用户界面展示。"""
    if isinstance(path, str) and path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _backup_content_label(info):
    """备份内容标签：完整备份显示会话数，修复备份显示仅核心数据。"""
    if getattr(info, "has_sessions", False):
        return "含会话(%d)" % getattr(info, "session_count", 0)
    return "仅核心数据"


def _fmt_ts(ts):
    if not ts: return ""
    try: return ts[:19].replace("T", " ")
    except: return ts

def launch(): MainWindow().mainloop()
