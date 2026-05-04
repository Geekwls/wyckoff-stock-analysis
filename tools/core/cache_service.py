#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一缓存服务 (Unified Cache Service)

解决问题：
1. 缓存散落在不同层（_analysis_cache, _index_analyzer_cache, stock_cache.json）
2. 失效策略不一致
3. 难以测试和并发控制

解决方案：
1. CacheService统一入口
2. 支持命名空间（analysis:*, symbol:*）
3. 明确失效策略
4. 可注入仓储模式
"""

import json
import hashlib
import time
import threading
from pathlib import Path
from typing import Any, Optional, Dict, Callable
from datetime import datetime, timedelta
from collections import OrderedDict
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """缓存条目"""

    def __init__(self, value: Any, ttl: int = None):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl  # Time to live in seconds
        self.hits = 0
        self.last_access = self.created_at

    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl is None:
            return False
        return time.time() > (self.created_at + self.ttl)

    def touch(self):
        """更新访问时间"""
        self.last_access = time.time()
        self.hits += 1


class CacheNamespace:
    """缓存命名空间"""

    ANALYSIS = "analysis"      # 分析结果缓存
    SYMBOL = "symbol"        # Symbol解析缓存
    DATA = "data"            # 数据源缓存
    INDEX = "index"          # 大盘数据缓存

    @classmethod
    def all(cls):
        return [cls.ANALYSIS, cls.SYMBOL, cls.DATA, cls.INDEX]


class CacheKey:
    """缓存键生成器"""

    @staticmethod
    def generate(namespace: str, *parts) -> str:
        """生成缓存键"""
        # 使用SHA256哈希确保键的唯一性和一致性
        key_str = ":".join([namespace] + [str(p) for p in parts])
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    @staticmethod
    def generate_version_key(symbol: str, period: str, data_timestamp: float) -> str:
        """生成版本键（基于数据时间戳）"""
        version_str = f"{symbol}:{period}:{int(data_timestamp)}"
        return hashlib.sha256(version_str.encode()).hexdigest()[:16]


class MemoryCache:
    """内存缓存（LRU）"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = threading.RLock()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0
        }

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self.lock:
            if key not in self.cache:
                self.stats["misses"] += 1
                return None

            entry = self.cache[key]

            # 检查是否过期
            if entry.is_expired():
                del self.cache[key]
                self.stats["misses"] += 1
                return None

            # LRU：移到末尾
            self.cache.move_to_end(key)
            entry.touch()
            self.stats["hits"] += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """设置缓存值"""
        with self.lock:
            # 检查容量
            if len(self.cache) >= self.max_size:
                # 删除最旧的项
                self.cache.popitem(last=False)
                self.stats["evictions"] += 1

            self.cache[key] = CacheEntry(value, ttl)
            return True

    def delete(self, key: str) -> bool:
        """删除缓存值"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self):
        """清空缓存"""
        with self.lock:
            self.cache.clear()
            self.stats = {"hits": 0, "misses": 0, "evictions": 0}

    def invalidate_namespace(self, namespace_prefix: str):
        """失效指定命名空间的所有缓存"""
        with self.lock:
            keys_to_delete = [
                key for key in self.cache.keys()
                if not key  # 哈希键不包含命名空间前缀，需要反向映射
            ]
            # 由于我们使用哈希键，这里简化为清空
            # 实际使用中应该维护key到namespace的映射
            self.cache.clear()

    def get_stats(self) -> Dict:
        """获取缓存统计"""
        with self.lock:
            total = self.stats["hits"] + self.stats["misses"]
            hit_rate = self.stats["hits"] / total if total > 0 else 0

            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "evictions": self.stats["evictions"],
                "hit_rate": round(hit_rate * 100, 2),
                "utilization": round(len(self.cache) / self.max_size * 100, 2)
            }


class FileCache:
    """文件缓存（持久化）"""

    def __init__(self, cache_dir: str = None):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        cache_file = self.cache_dir / f"{key}.json"

        if not cache_file.exists():
            return None

        try:
            with self.lock:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 检查是否过期
                if "expires_at" in data:
                    expires_at = data["expires_at"]
                    if time.time() > expires_at:
                        cache_file.unlink()
                        return None

                return data.get("value")
        except Exception as e:
            logger.warning(f"文件缓存读取失败 {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """设置缓存值"""
        cache_file = self.cache_dir / f"{key}.json"

        try:
            with self.lock:
                data = {
                    "value": value,
                    "created_at": time.time(),
                    "expires_at": time.time() + ttl if ttl else None
                }

                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)

                return True
        except Exception as e:
            logger.error(f"文件缓存写入失败 {key}: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除缓存值"""
        cache_file = self.cache_dir / f"{key}.json"

        with self.lock:
            if cache_file.exists():
                cache_file.unlink()
                return True
            return False

    def clear(self):
        """清空缓存"""
        with self.lock:
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    cache_file.unlink()
                except Exception as e:
                    logger.warning(f"删除缓存文件失败 {cache_file}: {e}")


class CacheService:
    """统一缓存服务"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, memory_max_size: int = 1000, cache_dir: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, memory_max_size: int = 1000, cache_dir: str = None):
        if self._initialized:
            return

        self.memory_cache = MemoryCache(max_size=memory_max_size)
        self.file_cache = FileCache(cache_dir=cache_dir)
        self.namespaces = {}  # namespace -> key list映射

        # TTL配置（秒）
        self.ttl_config = {
            CacheNamespace.ANALYSIS: 3600,      # 1小时
            CacheNamespace.SYMBOL: 86400,       # 24小时
            CacheNamespace.DATA: 300,           # 5分钟
            CacheNamespace.INDEX: 1800          # 30分钟
        }

        self._initialized = True

    @classmethod
    def get_instance(cls) -> 'CacheService':
        """获取单例实例"""
        return cls()

    def get(self, namespace: str, *key_parts, use_file: bool = False) -> Optional[Any]:
        """
        获取缓存值

        Args:
            namespace: 命名空间（analysis/symbol/data/index）
            *key_parts: 键组成部分
            use_file: 是否使用文件缓存（默认使用内存缓存）

        Returns:
            缓存值，不存在返回None
        """
        key = CacheKey.generate(namespace, *key_parts)

        # 优先从内存缓存获取
        if not use_file:
            value = self.memory_cache.get(key)
            if value is not None:
                return value

        # 从文件缓存获取
        value = self.file_cache.get(key)
        if value is not None and not use_file:
            # 回写到内存缓存
            self.memory_cache.set(key, value, ttl=self.ttl_config.get(namespace))

        return value

    def set(self, namespace: str, *key_parts, value: Any,
             ttl: int = None, use_file: bool = False) -> bool:
        """
        设置缓存值

        Args:
            namespace: 命名空间
            *key_parts: 键组成部分
            value: 缓存值
            ttl: 过期时间（秒），None使用默认配置
            use_file: 是否持久化到文件

        Returns:
            是否设置成功
        """
        key = CacheKey.generate(namespace, *key_parts)
        ttl = ttl or self.ttl_config.get(namespace)

        # 写入内存缓存
        self.memory_cache.set(key, value, ttl=ttl)

        # 写入文件缓存
        if use_file:
            return self.file_cache.set(key, value, ttl=ttl)

        return True

    def delete(self, namespace: str, *key_parts) -> bool:
        """删除缓存值"""
        key = CacheKey.generate(namespace, *key_parts)

        # 从内存缓存删除
        memory_deleted = self.memory_cache.delete(key)

        # 从文件缓存删除
        file_deleted = self.file_cache.delete(key)

        return memory_deleted or file_deleted

    def invalidate_namespace(self, namespace: str):
        """失效指定命名空间的所有缓存"""
        # 由于使用哈希键，这里简化处理
        # 实际使用中可以维护namespace->keys映射
        self.memory_cache.clear()
        self.file_cache.clear()

        logger.info(f"已失效命名空间: {namespace}")

    def invalidate_by_pattern(self, namespace: str, pattern: str):
        """按模式失效缓存"""
        # 简化实现：清空所有缓存
        # 实际应该遍历键并匹配模式
        self.memory_cache.clear()
        logger.info(f"已按模式失效缓存: {namespace}:{pattern}")

    def clear(self):
        """清空所有缓存"""
        self.memory_cache.clear()
        self.file_cache.clear()
        logger.info("已清空所有缓存")

    def get_stats(self) -> Dict:
        """获取缓存统计"""
        return {
            "memory_cache": self.memory_cache.get_stats(),
            "file_cache_dir": str(self.file_cache.cache_dir),
            "ttl_config": self.ttl_config
        }

    def warm_up(self, cache_data: Dict[str, Any]):
        """缓存预热"""
        for namespace_key, value in cache_data.items():
            # namespace_key格式: "namespace:part1:part2:..."
            parts = namespace_key.split(":")
            namespace = parts[0]
            key_parts = parts[1:]

            self.set(namespace, *key_parts, value=value)

        logger.info(f"缓存预热完成: {len(cache_data)}项")


class CachedDataFetcher:
    """带缓存的数据获取器（示例）"""

    def __init__(self, cache_service: CacheService = None):
        self.cache = cache_service or CacheService.get_instance()

    def fetch_data(self, symbol: str, period: str, force_refresh: bool = False):
        """
        获取数据（带缓存）

        Args:
            symbol: 股票代码
            period: 周期
            force_refresh: 是否强制刷新

        Returns:
            数据DataFrame
        """
        # 生成版本键
        version_key = CacheKey.generate_version_key(symbol, period, time.time())

        if not force_refresh:
            # 尝试从缓存获取
            cached_data = self.cache.get(CacheNamespace.DATA, symbol, period)
            if cached_data is not None:
                logger.info(f"使用缓存数据: {symbol} {period}")
                return cached_data

        # 实际获取数据
        logger.info(f"获取新数据: {symbol} {period}")
        # data = self._fetch_from_source(symbol, period)
        data = None  # 占位

        # 写入缓存
        if data is not None:
            self.cache.set(CacheNamespace.DATA, symbol, period, value=data, use_file=True)

        return data


# 使用示例
if __name__ == "__main__":
    # 创建缓存服务
    cache = CacheService(memory_max_size=500, cache_dir=".cache")

    # 设置缓存
    cache.set(CacheNamespace.ANALYSIS, "AAPL", "phase", value="Accumulation")
    cache.set(CacheNamespace.SYMBOL, "AAPL", value="AAPL_US")

    # 获取缓存
    result = cache.get(CacheNamespace.ANALYSIS, "AAPL", "phase")
    print(f"缓存结果: {result}")

    # 查看统计
    stats = cache.get_stats()
    print(f"缓存统计: {stats}")
