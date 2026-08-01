"""ProviderService: Provider 信息解析。整合 config + builtin + history。"""

from ..scanner.models import ScanResult, ProviderInfo, ProviderSource, ProviderStatus

BUILTIN_PROVIDERS = {"codex_local_access": {"name": "OpenAI Local Access", "base_url": "(built-in)", "model": "(managed by Codex)"}}


class ProviderService:
    @staticmethod
    def list_providers(result: ScanResult) -> list[dict]:
        """列出所有 Provider，含 config/builtin/history 三种来源。"""
        out = []
        seen = set()

        # config.toml 中定义的
        for name, info in result.defined_providers.items():
            seen.add(name)
            out.append({"name": name, "base_url": info.base_url, "model": result.current_model or "",
                        "source": ProviderSource.CONFIG.value, "status": ProviderStatus.AVAILABLE.value,
                        "thread_count": result.db_provider_distribution.get(name, 0)})

        # 内置
        for name, info in BUILTIN_PROVIDERS.items():
            if name not in seen:
                seen.add(name)
                out.append({"name": name, "base_url": info["base_url"], "model": info["model"],
                            "source": ProviderSource.BUILTIN.value, "status": ProviderStatus.AUTH_MANAGED.value,
                            "thread_count": result.db_provider_distribution.get(name, 0)})

        # 历史 thread 中出现但不在 config/builtin 中的
        for name, count in result.db_provider_distribution.items():
            if name and name not in seen:
                out.append({"name": name, "base_url": "(missing)", "model": "",
                            "source": ProviderSource.HISTORY_ONLY.value, "status": ProviderStatus.MISSING_CONFIG.value,
                            "thread_count": count})

        return out
