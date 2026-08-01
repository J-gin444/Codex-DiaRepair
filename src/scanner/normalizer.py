"""rollout_path 规范化工具。

Windows 下部分路径以 \\\\?\\ 前缀存储（长路径支持）。
本模块负责将 rollout_path 转换为标准可访问路径。
"""


def normalize_rollout_path(rollout_path: str | None) -> str:
    """规范化 rollout_path。

    处理规则：
    - 以 \\\\?\\ 开头：去掉该前缀
    - 其他：原样返回
    - None 或空字符串：返回空字符串

    Args:
        rollout_path: 原始路径，可能含 \\\\?\\ 前缀。

    Returns:
        规范化后的可访问路径。
    """
    if not rollout_path:
        return ""
    if rollout_path.startswith('\\\\?\\'):
        return rollout_path[4:]
    return rollout_path
