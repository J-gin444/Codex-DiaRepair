"""Thread list 视图。session=MainWindow, parent=容器Frame。"""

import tkinter as tk, tkinter.ttk as ttk

def build(session, parent):
    outer = ttk.Frame(parent, padding=10)
    outer.pack(fill=tk.BOTH, expand=True)

    # ---- 项目筛选栏 ----
    filter_bar = ttk.Frame(outer)
    filter_bar.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(filter_bar, text="项目").pack(side=tk.LEFT, padx=(0, 6))
    session.project_var = tk.StringVar(value="全部")
    project_cb = ttk.Combobox(filter_bar, textvariable=session.project_var, state="readonly", width=28)
    project_cb.pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(filter_bar, text="Provider").pack(side=tk.LEFT, padx=(0, 6))
    session.provider_filter_var = tk.StringVar(value="全部")
    provider_cb = ttk.Combobox(filter_bar, textvariable=session.provider_filter_var, state="readonly", width=18)
    provider_cb.pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(filter_bar, text="筛选", command=session._apply_filter).pack(side=tk.LEFT, padx=(0, 4))
    ttk.Button(filter_bar, text="清除", command=session._clear_filter).pack(side=tk.LEFT)
    ttk.Label(filter_bar, textvariable=session.count_var).pack(side=tk.LEFT, padx=(20, 12))
    ttk.Label(filter_bar, textvariable=session.memory_var).pack(side=tk.LEFT)

    # ---- 操作按钮 ----
    toolbar = ttk.Frame(outer)
    toolbar.pack(fill=tk.X, pady=(0, 8))
    sel_btn = ttk.Button(toolbar, text="全选", command=session.toggle_select_all)
    sel_btn.pack(side=tk.LEFT, padx=(0, 4))
    clear_btn = ttk.Button(toolbar, text="取消", command=session._clear_selection)
    clear_btn.pack(side=tk.LEFT, padx=(0, 8))
    setattr(session, "_sel_btn", sel_btn)
    setattr(session, "_clear_btn", clear_btn)

    # 删除模式
    ttk.Label(toolbar, text="删除方式").pack(side=tk.LEFT, padx=(8, 4))
    session.delete_mode_var = tk.StringVar(value="移入废纸篓")
    del_mode = ttk.Combobox(toolbar, textvariable=session.delete_mode_var,
                            values=["移入废纸篓", "彻底删除"], state="readonly", width=10)
    del_mode.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(toolbar, text="删除选中", command=session.delete_selected).pack(side=tk.LEFT)

    # ---- 双标签页 ----
    nb = ttk.Notebook(outer)
    nb.pack(fill=tk.BOTH, expand=True)

    cols = ("checked", "title", "provider", "size", "updated", "id")
    for tab_name, attr, label_text in [
        ("聊天窗口", "active_tree", "Active"),
        ("归档对话", "archived_tree", "Archived"),
    ]:
        frame = ttk.Frame(nb)
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
        tree.heading("checked", text="")
        tree.heading("title", text="标题")
        tree.heading("provider", text="Provider")
        tree.heading("size", text="大小")
        tree.heading("updated", text="更新时间")
        tree.heading("id", text="Thread ID")
        tree.column("checked", width=32, anchor="center", stretch=False)
        tree.column("title", width=320, anchor="w")
        tree.column("provider", width=80, anchor="center", stretch=False)
        tree.column("size", width=80, anchor="e", stretch=False)
        tree.column("updated", width=120, anchor="center", stretch=False)
        tree.column("id", width=220, anchor="w")

        scroll = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.bind("<Button-1>", lambda e, t=tree: session._on_click(e, t))
        setattr(session, attr, tree)
        nb.add(frame, text=label_text)
