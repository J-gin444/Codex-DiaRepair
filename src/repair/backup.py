"""BackupManager: 创建备份、校验、回滚。"""

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from .models import BackupSnapshot, BackupFile, RepairContext

MANIFEST_VERSION = "1.0"


class BackupManager:
    """管理备份目录的创建、校验和回滚。"""

    def __init__(self, backup_root: str = ""):
        self._backup_root = backup_root or os.path.join(os.getcwd(), "备份")

    def create_backup(self, context: RepairContext) -> BackupSnapshot:
        """创建完整备份。

        1. 创建唯一备份目录
        2. 复制 context.backup_scope 中的文件
        3. 计算 SHA256
        4. 生成 manifest.json
        5. 返回 BackupSnapshot
        """
        snapshot_path = self._make_snapshot_dir()
        created_at = datetime.now().isoformat()
        files: list[BackupFile] = []
        warnings: list[str] = []

        for file_path in context.backup_scope:
            original = os.path.normpath(file_path)
            dest_rel = _relative_dest(original, context.codex_path)
            dest_path = os.path.join(snapshot_path, dest_rel)

            bf = BackupFile(original_path=original, backup_path=dest_rel)

            if not os.path.isfile(original):
                warnings.append("%s not found" % original)
                files.append(bf)
                continue

            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(original, dest_path)
                bf.size = os.path.getsize(dest_path)
                bf.checksum = _sha256_file(dest_path)
            except OSError as e:
                warnings.append("failed to copy %s: %s" % (original, e))
                files.append(bf)
                continue

            # 对 SQLite 文件同时备份 wal/shm
            if original.endswith(".sqlite"):
                for suffix in ("-wal", "-shm"):
                    if suffix == "-shm":
                        # -shm 是 SQLite 共享内存索引，可再生且会随连接变化，
                        # 不纳入备份与校验，避免预览/校验时被改写导致校验失败。
                        continue
                    sidecar = original + suffix
                    if os.path.isfile(sidecar):
                        side_rel = _relative_dest(sidecar, context.codex_path)
                        side_dest = os.path.join(snapshot_path, side_rel)
                        os.makedirs(os.path.dirname(side_dest), exist_ok=True)
                        shutil.copy2(sidecar, side_dest)
                        bf2 = BackupFile(
                            original_path=sidecar,
                            backup_path=side_rel,
                            size=os.path.getsize(side_dest),
                            checksum=_sha256_file(side_dest),
                        )
                        files.append(bf2)

            files.append(bf)

        # 写 manifest
        manifest_path = os.path.join(snapshot_path, "manifest.json")
        manifest = {
            "version": MANIFEST_VERSION,
            "created_at": created_at,
            "source": context.codex_path,
            "warnings": warnings,
            "files": [
                {"original_path": f.original_path, "backup_path": f.backup_path,
                 "sha256": f.checksum, "size": f.size}
                for f in files if f.checksum
            ],
        }
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)

        return BackupSnapshot(
            path=snapshot_path,
            created_at=created_at,
            source=context.codex_path,
            manifest_path=manifest_path,
            files=files,
            verified=self.verify_backup(snapshot_path, manifest),
        )

    def verify_backup(self, snapshot_path: str, manifest: dict | None = None) -> bool:
        """校验备份完整性。

        如果未传入 manifest，从 manifest.json 读取。
        """
        if manifest is None:
            manifest_path = os.path.join(snapshot_path, "manifest.json")
            if not os.path.isfile(manifest_path):
                return False
            try:
                with open(manifest_path, "r", encoding="utf-8") as mf:
                    manifest = json.load(mf)
            except (OSError, json.JSONDecodeError):
                return False

        for entry in manifest.get("files", []):
            if entry.get("backup_path", "").endswith("-shm"):
                continue  # 旧备份兼容：跳过 -shm 条目
            backup_file = os.path.join(snapshot_path, entry["backup_path"])
            if not os.path.isfile(backup_file):
                return False
            if os.path.getsize(backup_file) != entry.get("size", 0):
                return False
            if _sha256_file(backup_file) != entry.get("sha256", ""):
                return False

        return True

    def rollback(self, snapshot: BackupSnapshot) -> tuple[bool, list[str]]:
        """从 BackupSnapshot 恢复所有文件。

        逐文件从 backup_path 复制回 original_path，恢复后校验 SHA256。

        Returns:
            (成功标志, 失败文件列表)
        """
        failed: list[str] = []

        for bf in snapshot.files:
            if not bf.checksum:
                continue  # 未成功备份的文件跳过
            source = os.path.join(snapshot.path, bf.backup_path)
            if not os.path.isfile(source):
                failed.append(bf.original_path + " (backup missing)")
                continue

            try:
                shutil.copy2(source, bf.original_path)
            except OSError as e:
                failed.append(bf.original_path + " (copy failed: %s)" % e)
                continue

            # 恢复后校验
            restored_checksum = _sha256_file(bf.original_path)
            if restored_checksum != bf.checksum:
                failed.append(bf.original_path + " (checksum mismatch)")

        return len(failed) == 0, failed

    def _make_snapshot_dir(self) -> str:
        """创建唯一的备份子目录。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        hex_id = uuid.uuid4().hex[:6]
        dir_name = "%s_%s" % (ts, hex_id)
        path = os.path.join(self._backup_root, dir_name)
        os.makedirs(path, exist_ok=True)
        return path


def _sha256_file(filepath: str) -> str:
    """计算文件的 SHA256 哈希。"""
    sha = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                sha.update(chunk)
    except OSError:
        return ""
    return sha.hexdigest()


def _relative_dest(path: str, root: str) -> str:
    """计算备份目标在快照目录内的相对路径。

    文件位于 codex_home 下时保留相对子路径（如 sessions/2026/07/x.jsonl），
    避免不同子目录的同名文件互相覆盖；目录外文件退回文件名。
    """
    try:
        rel = os.path.relpath(path, root)
        if rel == ".." or rel.startswith(".." + os.sep):
            return os.path.basename(path)
        return rel
    except ValueError:
        return os.path.basename(path)
