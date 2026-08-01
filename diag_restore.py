import json, os, sqlite3

trash_dir = r'D:\projects\DiaRepair\备份\trash'
entries = [d for d in os.listdir(trash_dir) if os.path.isdir(os.path.join(trash_dir, d))]
if not entries:
    print('Trash empty - 请先在 GUI 中移入废纸篓一个对话再运行')
else:
    tid = entries[0]
    meta_path = os.path.join(trash_dir, tid, 'metadata.json')
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    print('=== 废纸篓中第一条 ===')
    print('thread_id:', meta['thread_id'])
    rp = meta.get('original_rollout_path','')
    print('original_rollout_path:', rp)

    db = os.path.expanduser(r'~/.codex/state_5.sqlite')
    con = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    row = con.execute('SELECT id, title, model_provider, rollout_path, archived, updated_at_ms FROM threads WHERE id=?', (tid,)).fetchone()
    con.close()
    print()
    print('=== DB 中当前状态 ===')
    if row:
        print('存在: id=%s title=%s provider=%s archived=%s' % (row[0], row[1], row[2], row[4]))
        print('  rollout_path=%s' % row[3])
    else:
        print('不存在')

    if rp:
        prefix = '\\\\?\\'
        norm = rp
        if norm.startswith(prefix):
            norm = norm[4:]
        print()
        print('=== Rollout 文件 ===')
        print('normalized:', norm)
        print('exists:', os.path.isfile(norm))

    idx = os.path.expanduser(r'~/.codex/session_index.jsonl')
    found = False
    if os.path.isfile(idx):
        with open(idx, 'r', encoding='utf-8') as f:
            for line in f:
                if tid in line:
                    found = True; break
    print()
    print('=== session_index.jsonl ===')
    print('has entry:', found)
