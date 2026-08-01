"""config.toml 解析模块。

基于行级解析，不依赖外部 toml 解析库。
支持 INI 风格的节头 ([...]) 和键值对 (key = value)。
"""

import os
import re
from .models import ProviderInfo
from .exceptions import ConfigParseError


def read_config(codex_home: str) -> tuple[str | None, str | None, dict[str, ProviderInfo], list[str], list[str]]:
    """读取并解析 config.toml。

    Args:
        codex_home: .codex 目录路径。

    Returns:
        (current_provider, current_model, defined_providers, errors, warnings)

        current_provider: 顶层 model_provider 的值，不存在时为 None
        current_model: 顶层 model 的值，不存在时为 None
        defined_providers: {provider_name: ProviderInfo}
        errors: 解析错误列表
        warnings: 警告列表
    """
    config_path = os.path.join(codex_home, "config.toml")
    if not os.path.isfile(config_path):
        return None, None, {}, ["config.toml not found: %s" % config_path], []

    try:
        with open(config_path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return None, None, {}, ["Failed to read config.toml: %s" % e], []

    # 行级解析
    lines = text.splitlines()
    return _parse_config_lines(lines, config_path)


def _parse_config_lines(lines: list[str], config_path: str) -> tuple[str | None, str | None, dict[str, ProviderInfo], list[str], list[str]]:
    """解析 config.toml 的行内容。

    解析规则：
    - 识别顶层 key = value 键值对
    - 识别 [section] 节头
    - 将 [model_providers.xxx] 节的内容提取为 ProviderInfo
    """
    errors: list[str] = []
    warnings: list[str] = []

    current_provider: str | None = None
    current_model: str | None = None
    defined_providers: dict[str, ProviderInfo] = {}

    in_provider_section = False
    current_section_name = ""
    current_section_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # 跳过空行和注释
        if not stripped or stripped.startswith("#"):
            continue

        # 检测节头
        section_match = re.match(r'^\[(.+)\]$', stripped)
        if section_match:
            # 保存前一个 provider 节
            if in_provider_section and current_section_name:
                provider = _build_provider_info(current_section_name, current_section_lines)
                defined_providers[provider.section_name] = provider

            section_header = section_match.group(1)
            in_provider_section = section_header.startswith("model_providers.")
            if in_provider_section:
                current_section_name = section_header[len("model_providers."):].strip()
                # 去掉引号（TOML 支持 "xxx" 和 'xxx' 格式）
                if (current_section_name.startswith('"') and current_section_name.endswith('"')) or \
                   (current_section_name.startswith("'") and current_section_name.endswith("'")):
                    current_section_name = current_section_name[1:-1]
                current_section_lines = []
            continue

        # 在 provider 节内收集行
        if in_provider_section:
            current_section_lines.append(line)
            continue

        # 顶层键值对
        kv_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$', stripped)
        if kv_match:
            key = kv_match.group(1)
            value = _strip_toml_value(kv_match.group(2).strip())
            if key == "model_provider":
                current_provider = value
            elif key == "model":
                current_model = value

    # 处理最后一个 provider 节
    if in_provider_section and current_section_name:
        provider = _build_provider_info(current_section_name, current_section_lines)
        defined_providers[provider.section_name] = provider

    return current_provider, current_model, defined_providers, errors, warnings


def _strip_toml_value(value: str) -> str:
    """去除 TOML 值的引号包裹。"""
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _build_provider_info(section_name: str, lines: list[str]) -> ProviderInfo:
    """从节内行构建 ProviderInfo 对象。

    同时保留原始行文本（用于别名生成的 raw_section）。
    """
    info = ProviderInfo(section_name=section_name)
    raw_lines = ["[model_providers.%s]" % section_name]

    for line in lines:
        raw_lines.append(line)
        stripped = line.strip()
        kv_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)$', stripped)
        if not kv_match:
            continue
        key = kv_match.group(1)
        value = _strip_toml_value(kv_match.group(2).strip())

        if key == "name":
            info.name = value
        elif key == "base_url":
            info.base_url = value
        elif key == "wire_api":
            info.wire_api = value
        elif key == "requires_openai_auth":
            info.requires_openai_auth = value.lower() in ("true", "1", "yes")
        elif key == "experimental_bearer_token":
            info.experimental_bearer_token = value

    info.raw_section = "\n".join(raw_lines)
    return info
