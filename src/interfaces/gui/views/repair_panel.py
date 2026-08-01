"""Repair panel 视图。"""

import tkinter as tk, tkinter.ttk as ttk

def build(session, parent):
    outer = ttk.Frame(parent, padding=10)
    outer.pack(fill=tk.BOTH, expand=True)

    # ---- Provider 信息 ----
    prov = ttk.LabelFrame(outer, text="当前 Provider 信息", padding=6)
    prov.pack(fill=tk.X, pady=(0, 6))
    session.provider_info_var = tk.StringVar(value="未扫描")
    ttk.Label(prov, textvariable=session.provider_info_var).pack(anchor="w")

    # ---- 缺失 Provider 配置 ----
    missing_frame = ttk.LabelFrame(outer, text="缺失 Provider 处理", padding=6)
    missing_frame.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(missing_frame, textvariable=session.missing_prov_var).pack(anchor="w")

    cfg = ttk.Frame(missing_frame)
    cfg.pack(fill=tk.X, pady=(4, 0))
    ttk.Label(cfg, text="处理方式").pack(side=tk.LEFT, padx=(0, 6))
    session.provider_mode_var = tk.StringVar(value="映射到已有")
    mode_cb = ttk.Combobox(cfg, textvariable=session.provider_mode_var,
                           values=["映射到已有", "新增配置", "删除历史"], state="readonly", width=12)
    mode_cb.pack(side=tk.LEFT, padx=(0, 12))

    ttk.Label(cfg, text="目标").pack(side=tk.LEFT, padx=(0, 4))
    session.target_provider_var = tk.StringVar(value="custom")
    session.target_provider_cb = ttk.Combobox(cfg, textvariable=session.target_provider_var, state="readonly", width=16)
    session.target_provider_cb.pack(side=tk.LEFT, padx=(0, 12))

    ttk.Button(cfg, text="应用", command=session._apply_provider_config).pack(side=tk.LEFT)

    # ---- 诊断结果 ----
    sf = ttk.LabelFrame(outer, text="诊断结果", padding=6)
    sf.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(sf, textvariable=session.diag_summary_var).pack(anchor="w")
    ttk.Label(sf, textvariable=session.diag_detail_var, foreground="gray").pack(anchor="w", pady=(2, 0))

    # ---- 操作按钮 ----
    bf = ttk.Frame(outer)
    bf.pack(fill=tk.X, pady=(0, 6))
    ttk.Button(bf, text="刷新诊断", command=session.refresh_diagnosis).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(bf, text="执行修复", command=session.repair).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Label(bf, textvariable=session.repair_status_var).pack(side=tk.LEFT, padx=(12, 0))

    # ---- Issue 列表 ----
    cols = ("severity", "type", "summary", "hint")
    tree = ttk.Treeview(outer, columns=cols, show="headings", height=8)
    tree.heading("severity", text="级别")
    tree.heading("type", text="类型")
    tree.heading("summary", text="描述")
    tree.heading("hint", text="修复方向")
    tree.column("severity", width=60, anchor="center", stretch=False)
    tree.column("type", width=160, anchor="w", stretch=False)
    tree.column("summary", width=380, anchor="w")
    tree.column("hint", width=180, anchor="w")
    scroll = ttk.Scrollbar(outer, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    setattr(session, "issue_tree", tree)
