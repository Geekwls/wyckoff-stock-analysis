#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""缓存一致性测试：统一接口与兼容接口的TTL/失效行为一致。"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.wyckoff.core.cache import LRUCache
from src.wyckoff.core.cache_service import CacheService, CacheNamespace


def _reset_cache_singleton():
    CacheService._instance = None


def test_cache_ttl_consistency_across_paths():
    """同一 key 在不同调用路径（兼容LRU vs 统一服务）TTL行为一致。"""
    _reset_cache_singleton()
    service = CacheService(memory_max_size=128)
    legacy = LRUCache(max_size=128, ttl_seconds=1)

    key = "consistency-key"
    value = {"ok": True}

    legacy.put(key, value)
    service.set(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key, value=value, ttl=1)

    assert legacy.get(key) == value
    assert service.get(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key) == value

    time.sleep(1.2)

    assert legacy.get(key) is None
    assert service.get(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key) is None


def test_cache_invalidation_consistency_across_paths():
    """同一 key 在不同调用路径上失效行为一致。"""
    _reset_cache_singleton()
    service = CacheService(memory_max_size=128)
    legacy = LRUCache(max_size=128, ttl_seconds=60)

    key = "invalidate-key"
    value = "v1"

    legacy.put(key, value)
    assert service.get(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key) == value

    service.delete(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key)
    assert legacy.get(key) is None

    legacy.put(key, value)
    legacy.invalidate(key)
    assert service.get(CacheNamespace.ANALYSIS, legacy._adapter._instance_prefix, key) is None
