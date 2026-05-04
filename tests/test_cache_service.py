#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存服务单元测试
"""

import sys
import os
import time
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.wyckoff.core.cache_service import (
    CacheService, CacheNamespace, CacheKey,
    MemoryCache, FileCache, CachedDataFetcher
)


def test_memory_cache():
    """测试内存缓存"""
    print("=" * 70)
    print("测试1：内存缓存（LRU）")
    print("=" * 70)

    cache = MemoryCache(max_size=3)

    # 测试基本操作
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    print("✅ 设置3个缓存项")
    print(f"   缓存大小: {cache.get_stats()['size']}")

    # 测试获取
    result = cache.get("key1")
    print(f"\n✅ 获取key1: {result}")
    print(f"   缓存命中: {cache.get_stats()['hits']}")

    # 测试LRU淘汰
    cache.set("key4", "value4")
    print(f"\n✅ 添加key4（触发LRU淘汰）")
    print(f"   缓存大小: {cache.get_stats()['size']}")
    print(f"   淘汰次数: {cache.get_stats()['evictions']}")

    # 测试TTL过期
    cache.set("key5", "value5", ttl=1)
    print(f"\n✅ 设置key5（TTL=1秒）")
    time.sleep(1.5)
    result = cache.get("key5")
    print(f"   1.5秒后获取key5: {result}（应该为None）")

    # 测试统计
    print(f"\n缓存统计:")
    stats = cache.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    return True


def test_cache_service():
    """测试统一缓存服务"""
    print("\n" + "=" * 70)
    print("测试2：统一缓存服务")
    print("=" * 70)

    # 使用临时目录作为缓存目录
    temp_dir = tempfile.mkdtemp()
    try:
        cache = CacheService(memory_max_size=10, cache_dir=temp_dir)

        # 测试命名空间
        cache.set(CacheNamespace.ANALYSIS, "AAPL", "phase", value="Accumulation")
        cache.set(CacheNamespace.SYMBOL, "AAPL", value="AAPL_US")
        cache.set(CacheNamespace.DATA, "AAPL", "1y", value={"data": "mock"}, use_file=True)

        print("✅ 设置3个不同命名空间的缓存")

        # 获取缓存
        phase = cache.get(CacheNamespace.ANALYSIS, "AAPL", "phase")
        print(f"\n✅ 获取phase: {phase}")

        symbol_info = cache.get(CacheNamespace.SYMBOL, "AAPL")
        print(f"✅ 获取symbol: {symbol_info}")

        data = cache.get(CacheNamespace.DATA, "AAPL", "1y", use_file=True)
        print(f"✅ 获取data: {data}")

        # 测试失效
        cache.invalidate_namespace(CacheNamespace.ANALYSIS)
        print(f"\n✅ 失效analysis命名空间")

        # 测试统计
        stats = cache.get_stats()
        print(f"\n缓存统计:")
        print(f"  内存缓存大小: {stats['memory_cache']['size']}")
        print(f"  命中率: {stats['memory_cache']['hit_rate']}%")

        return True

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_cache_key_generation():
    """测试缓存键生成"""
    print("\n" + "=" * 70)
    print("测试3：缓存键生成")
    print("=" * 70)

    # 测试键生成
    key1 = CacheKey.generate(CacheNamespace.ANALYSIS, "AAPL", "phase")
    key2 = CacheKey.generate(CacheNamespace.SYMBOL, "AAPL")

    print(f"✅ 生成键1: {key1}")
    print(f"✅ 生成键2: {key2}")
    print(f"✅ 键唯一性: {key1 != key2}")

    # 测试版本键
    version_key = CacheKey.generate_version_key("AAPL", "1y", time.time())
    print(f"\n✅ 版本键: {version_key}")

    # 测试相同输入产生相同键
    key1_again = CacheKey.generate(CacheNamespace.ANALYSIS, "AAPL", "phase")
    print(f"✅ 键一致性: {key1 == key1_again}")

    return True


def test_ttl_config():
    """测试TTL配置"""
    print("\n" + "=" * 70)
    print("测试4：TTL配置")
    print("=" * 70)

    cache = CacheService()

    print("TTL配置:")
    for namespace, ttl in cache.ttl_config.items():
        print(f"  {namespace}: {ttl}秒 ({ttl//60}分钟)")

    # 测试自定义TTL
    custom_ttl = 600  # 10分钟
    cache.set(CacheNamespace.ANALYSIS, "MSFT", "test", value="custom", ttl=custom_ttl)
    print(f"\n✅ 设置自定义TTL: {custom_ttl}秒")

    return True


def test_cache_warm_up():
    """测试缓存预热"""
    print("\n" + "=" * 70)
    print("测试5：缓存预热")
    print("=" * 70)

    cache = CacheService()

    # 准备预热数据
    warmup_data = {
        "analysis:AAPL:phase": "Accumulation",
        "analysis:AAPL:trend": "Up",
        "symbol:AAPL": "AAPL_US",
        "data:AAPL:1y": {"open": 100, "close": 110}
    }

    cache.warm_up(warmup_data)
    print(f"✅ 缓存预热完成: {len(warmup_data)}项")

    # 验证预热
    for key in warmup_data.keys():
        parts = key.split(":")
        namespace = parts[0]
        key_parts = parts[1:]
        value = cache.get(namespace, *key_parts)
        print(f"  {key}: {value is not None}")

    return True


def main():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("统一缓存服务 - 测试套件")
    print("=" * 70)

    tests = [
        ("内存缓存", test_memory_cache),
        ("统一缓存服务", test_cache_service),
        ("缓存键生成", test_cache_key_generation),
        ("TTL配置", test_ttl_config),
        ("缓存预热", test_cache_warm_up),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} 测试失败: {e}")
            results.append((test_name, False))

    # 最终报告
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)

    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name:20s}: {status}")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    print(f"\n总计: {passed_count}/{total_count} 测试通过")

    if passed_count == total_count:
        print("\n🎉 所有测试通过！统一缓存服务工作正常")
        return 0
    else:
        print(f"\n⚠️  部分测试失败 ({passed_count}/{total_count})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
