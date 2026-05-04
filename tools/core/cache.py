"""
旧缓存接口兼容层。

说明：
- 历史上项目通过 `LRUCache` 直接做分析缓存。
- 现在统一由 `CacheService` 管理缓存策略与命名空间。
- 该模块仅保留薄封装，避免“双实现并存”。
"""
from typing import Any, Callable

from .cache_service import CacheService


class LRUCache:
    """兼容旧接口：内部转发到 CacheService 的 LegacyLRUAdapter。"""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 3600):
        self._adapter = CacheService.get_instance().get_legacy_lru_adapter(
            namespace="analysis",
            max_size=max_size,
            ttl_seconds=ttl_seconds,
        )

    def get(self, key: str):
        return self._adapter.get(key)

    def put(self, key: str, value: Any) -> None:
        self._adapter.put(key, value)

    def get_or_compute(self, key: str, compute_fn: Callable, *args, **kwargs):
        return self._adapter.get_or_compute(key, compute_fn, *args, **kwargs)

    def invalidate(self, key: str = None) -> None:
        self._adapter.invalidate(key)
