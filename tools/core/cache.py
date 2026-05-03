"""
威科夫分析系统缓存模块
提供线程安全的LRU缓存，支持TTL和容量限制
"""
from collections import OrderedDict
from threading import Lock
from typing import Any, Optional, Callable
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class LRUCache:
    """
    线程安全的LRU缓存，支持TTL（生存时间）
    
    特性:
    - 容量限制：超出容量时淘汰最久未使用的条目
    - TTL过期：条目超过指定时间后自动失效
    - 线程安全：支持多线程并发访问
    - 统计信息：提供命中率等统计
    """
    
    def __init__(self, max_size: int = 256, ttl_seconds: int = 3600):
        """
        初始化LRU缓存
        
        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 条目生存时间（秒）
        """
        self._cache: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()
        self._max_size = max_size
        self._ttl = timedelta(seconds=ttl_seconds)
        self._lock = Lock()
        
        # 统计信息
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存值，如果不存在或已过期则返回None
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            value, timestamp = self._cache[key]
            
            # 检查是否过期
            if datetime.now() - timestamp > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None
            
            # 移到末尾（最近使用）
            self._cache.move_to_end(key)
            self._hits += 1
            return value
    
    def put(self, key: str, value: Any) -> None:
        """
        存入缓存
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            
            self._cache[key] = (value, datetime.now())
            
            # 超出容量则淘汰最久未使用的
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)
    
    def get_or_compute(self, key: str, compute_fn: Callable, *args, **kwargs) -> Any:
        """
        获取或计算缓存值
        
        Args:
            key: 缓存键
            compute_fn: 计算函数
            *args, **kwargs: 传递给计算函数的参数
            
        Returns:
            缓存值或计算结果
        """
        value = self.get(key)
        if value is not None:
            return value
        
        value = compute_fn(*args, **kwargs)
        self.put(key, value)
        return value
    
    def invalidate(self, key: str = None) -> None:
        """
        清除缓存
        
        Args:
            key: 要清除的键，如果为None则清除所有
        """
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()
    
    def clear_expired(self) -> int:
        """
        清除所有过期条目
        
        Returns:
            清除的条目数量
        """
        cleared = 0
        with self._lock:
            now = datetime.now()
            expired_keys = [
                k for k, (_, ts) in self._cache.items()
                if now - ts > self._ttl
            ]
            for k in expired_keys:
                del self._cache[k]
                cleared += 1
        return cleared
    
    @property
    def size(self) -> int:
        """当前缓存大小"""
        return len(self._cache)
    
    @property
    def hit_rate(self) -> float:
        """缓存命中率"""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total
    
    @property
    def stats(self) -> dict:
        """缓存统计信息"""
        return {
            'size': self.size,
            'max_size': self._max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(self.hit_rate, 4),
            'ttl_seconds': self._ttl.total_seconds()
        }
    
    def __repr__(self) -> str:
        return f"LRUCache(size={self.size}/{self._max_size}, hit_rate={self.hit_rate:.2%})"
