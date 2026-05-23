"""缓存服务单元测试"""

import time
import tempfile
import shutil

from wyckoff.core.cache_service import (
    CacheKey,
    CacheNamespace,
    CacheService,
    MemoryCache,
)


def test_memory_cache_lru_and_ttl():
    cache = MemoryCache(max_size=3)

    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")
    assert cache.get_stats()["size"] == 3
    assert cache.get("key1") == "value1"
    assert cache.get_stats()["hits"] == 1

    cache.set("key4", "value4")
    assert cache.get_stats()["size"] == 3
    assert cache.get_stats()["evictions"] == 1

    cache.set("key5", "value5", ttl=1)
    time.sleep(1.5)
    assert cache.get("key5") is None


def test_cache_service_namespaces_and_invalidation():
    temp_dir = tempfile.mkdtemp()
    try:
        cache = CacheService(memory_max_size=10, cache_dir=temp_dir)

        cache.set(CacheNamespace.ANALYSIS, "AAPL", "phase", value="Accumulation")
        cache.set(CacheNamespace.SYMBOL, "AAPL", value="AAPL_US")
        cache.set(
            CacheNamespace.DATA,
            "AAPL",
            "1y",
            value={"data": "mock"},
            use_file=True,
        )

        assert cache.get(CacheNamespace.ANALYSIS, "AAPL", "phase") == "Accumulation"
        assert cache.get(CacheNamespace.SYMBOL, "AAPL") == "AAPL_US"
        assert cache.get(CacheNamespace.DATA, "AAPL", "1y", use_file=True) == {
            "data": "mock"
        }

        cache.invalidate_namespace(CacheNamespace.ANALYSIS)
        assert cache.get(CacheNamespace.ANALYSIS, "AAPL", "phase") is None
        assert cache.get(CacheNamespace.SYMBOL, "AAPL") == "AAPL_US"

        stats = cache.get_stats()
        assert "memory_cache" in stats
        assert stats["memory_cache"]["size"] >= 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_cache_key_generation():
    key1 = CacheKey.generate(CacheNamespace.ANALYSIS, "AAPL", "phase")
    key2 = CacheKey.generate(CacheNamespace.SYMBOL, "AAPL")
    assert key1 != key2

    version_key = CacheKey.generate_version_key("AAPL", "1y", time.time())
    assert version_key.startswith("version_")

    key1_again = CacheKey.generate(CacheNamespace.ANALYSIS, "AAPL", "phase")
    assert key1 == key1_again


def test_ttl_config_and_custom_ttl():
    cache = CacheService()
    assert CacheNamespace.ANALYSIS in cache.ttl_config
    assert cache.ttl_config[CacheNamespace.ANALYSIS] == 3600

    custom_ttl = 600
    cache.set(
        CacheNamespace.ANALYSIS,
        "MSFT",
        "test",
        value="custom",
        ttl=custom_ttl,
    )
    assert cache.get(CacheNamespace.ANALYSIS, "MSFT", "test") == "custom"


def test_cache_warm_up():
    cache = CacheService()
    warmup_data = {
        "analysis:AAPL:phase": "Accumulation",
        "analysis:AAPL:trend": "Up",
        "symbol:AAPL": "AAPL_US",
        "data:AAPL:1y": {"open": 100, "close": 110},
    }

    cache.warm_up(warmup_data)

    assert cache.get(CacheNamespace.ANALYSIS, "AAPL", "phase") == "Accumulation"
    assert cache.get(CacheNamespace.ANALYSIS, "AAPL", "trend") == "Up"
    assert cache.get(CacheNamespace.SYMBOL, "AAPL") == "AAPL_US"
    assert cache.get(CacheNamespace.DATA, "AAPL", "1y") == {"open": 100, "close": 110}
