"""认证状态读取模块。

只读取登录方式的"模式标记"（forced_login_method、preferred_auth_method、
auth.json 的 auth_mode），绝不读取或暴露 token 等敏感内容。
"""

import json
import os
import re
from .models import AuthState


def read_auth_state(codex_home: str) -> AuthState:
    """读取 config.toml 的认证相关键和 auth.json 的登录模式。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        AuthState: 只含模式标记的认证状态。
    """
    state = AuthState(
        config_path=os.path.join(codex_home, "config.toml"),
        auth_json_path=os.path.join(codex_home, "auth.json"),
    )

    if os.path.isfile(state.config_path):
        try:
            with open(state.config_path, "r", encoding="utf-8-sig", errors="replace") as f:
                _parse_top_level_auth(f.read(), state)
        except OSError:
            pass

    if os.path.isfile(state.auth_json_path):
        try:
            with open(state.auth_json_path, "r", encoding="utf-8-sig", errors="replace") as f:
                obj = json.load(f)
        except (OSError, json.JSONDecodeError):
            obj = None
        if isinstance(obj, dict):
            state.cached_auth_mode = str(obj.get("auth_mode") or "")
            tokens = obj.get("tokens")
            state.has_cached_chatgpt_tokens = bool(
                isinstance(tokens, dict)
                and tokens.get("access_token")
                and tokens.get("refresh_token")
            )

    return state


def _parse_top_level_auth(text: str, state: AuthState) -> None:
    """解析 config.toml 顶层（非 [section] 内）的认证相关键值对。"""
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^\[.+\]$", stripped):
            in_section = True
            continue
        if in_section:
            continue
        kv = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$", stripped)
        if not kv:
            continue
        key = kv.group(1)
        value = _strip_quotes(kv.group(2).strip())
        if key == "forced_login_method":
            state.forced_login_method = value.lower()
        elif key == "preferred_auth_method":
            state.preferred_auth_method = value.lower()
        elif key == "disable_response_storage":
            state.disable_response_storage = value.lower() in ("true", "1", "yes")


def _strip_quotes(value: str) -> str:
    """去除 TOML 字符串值的引号包裹。"""
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
