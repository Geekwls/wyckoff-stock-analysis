"""
信号生命周期管理：pending → confirmed / expired

每个信号触发时拍快照，后续逐日检查是否被确认或失效。

孟洪涛原则：信号质量会随着时间衰减
"""
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import math

from types import MappingProxyType

SIGNAL_TTL: Dict[str, int] = MappingProxyType({
    "spring": 3,
    "sos": 2,
    "lps": 3,
    "lpsy": 3,
    "joc": 2,
    "fti": 2,
})

# 信号衰减参数（孟洪涛原则）
SIGNAL_DECAY_CONFIG: Dict[str, Dict] = MappingProxyType({
    "spring": {
        "half_life": 5,      # 半衰期（天）
        "max_decay": 0.3,    # 最小保留比例
        "critical_days": 7,  # 临界天数
    },
    "joc": {
        "half_life": 4,
        "max_decay": 0.4,
        "critical_days": 6,
    },
    "sos": {
        "half_life": 3,
        "max_decay": 0.3,
        "critical_days": 5,
    },
    "sow": {
        "half_life": 3,
        "max_decay": 0.3,
        "critical_days": 5,
    },
    "lps": {
        "half_life": 4,
        "max_decay": 0.4,
        "critical_days": 6,
    },
    "lpsy": {
        "half_life": 4,
        "max_decay": 0.4,
        "critical_days": 6,
    },
    "fti": {
        "half_life": 3,
        "max_decay": 0.3,
        "critical_days": 5,
    },
})


def build_snapshot(
    signal_type: str,
    price: float,
    low: float,
    high: float,
    volume: float,
    support: float,
    resistance: float,
) -> Dict:
    return {
        "signal_type": signal_type,
        "snap_price": price,
        "snap_low": low,
        "snap_high": high,
        "snap_volume": volume,
        "snap_support": support,
        "snap_resistance": resistance,
    }


def check_confirmation(
    signal_type: str,
    snap: Dict,
    today_low: float,
    today_high: float,
    today_close: float,
    today_volume: float,
    days_elapsed: int,
) -> Tuple[str, str]:
    """
    返回 (status, reason)。
    status ∈ {"pending", "confirmed", "expired"}
    """
    ttl = SIGNAL_TTL.get(signal_type, 3)
    if days_elapsed > ttl:
        return "expired", f"TTL {ttl}天已到，未满足确认条件"

    if signal_type == "spring":
        return _check_spring(snap, today_low, today_close, today_volume, days_elapsed)
    elif signal_type == "sos":
        return _check_sos(snap, today_low, today_close, today_volume, days_elapsed)
    elif signal_type == "lps":
        return _check_lps(snap, today_low, today_close, today_volume, days_elapsed)
    elif signal_type == "lpsy":
        return _check_lpsy(snap, today_high, today_close, days_elapsed)
    elif signal_type == "joc":
        return _check_joc(snap, today_low, today_close, today_volume, days_elapsed)
    elif signal_type == "fti":
        return _check_fti(snap, today_high, today_close, today_volume, days_elapsed)
    elif signal_type == "sow":
        return _check_sow(snap, today_high, today_close, today_volume, days_elapsed)
    return "pending", "等待确认"


def _check_spring(snap: Dict, low: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    support = snap["snap_support"]
    if low < support * 0.98:
        return "expired", f"跌破支撑 {support:.2f}"
    if close > support and volume < snap["snap_volume"] * 1.2:
        return "confirmed", f"守住支撑 {support:.2f}，缩量确认"
    if days >= 2:
        return "expired", f"{days}天内未确认"
    return "pending", "等待站稳支撑"


def _check_sos(snap: Dict, low: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    snap_low = snap["snap_low"]
    if low < snap_low:
        return "expired", f"跌破信号日低点 {snap_low:.2f}"
    if volume < snap["snap_volume"] * 0.8 and close >= snap["snap_price"] * 0.97:
        return "confirmed", f"缩量回踩确认"
    if days >= 2:
        return "expired", f"{days}天内未缩量回踩"
    return "pending", "等待缩量回踩"


def _check_lps(snap: Dict, low: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    ma20 = snap["snap_support"]
    if low < ma20 * 0.98:
        return "expired", f"跌破 MA20 {ma20:.2f}"
    if volume > snap["snap_volume"] * 1.5:
        return "expired", "异常放量，LPS 逻辑失效"
    if close >= ma20 and volume <= snap["snap_volume"] * 1.2:
        return "confirmed", f"站稳 MA20 {ma20:.2f}，缩量确认"
    return "pending", "等待站稳 MA20"


def _check_lpsy(snap: Dict, high: float, close: float, days: int) -> Tuple[str, str]:
    resistance = snap["snap_resistance"]
    if high > resistance * 1.02:
        return "expired", f"突破阻力 {resistance:.2f}，LPSY 失效"
    if close < snap["snap_support"] * 0.98:
        return "confirmed", f"跌破冰线 {snap['snap_support']:.2f}"
    return "pending", "等待跌破冰线"


def _check_joc(snap: Dict, low: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    """JOC 确认：突破前期阻力后缩量回踩未跌回，量价配合"""
    resistance = snap["snap_resistance"]
    snap_close = snap["snap_price"]
    if low < resistance * 0.97:
        return "expired", f"跌回阻力 {resistance:.2f} 以内，JOC 失败"
    if close >= resistance and volume <= snap["snap_volume"] * 1.1:
        return "confirmed", f"站稳阻力 {resistance:.2f}，缩量测试确认"
    if close >= resistance:
        return "pending", "等待缩量回踩确认"
    return "pending", "等待站稳阻力位"


def _check_fti(snap: Dict, high: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    """FTI 确认：跌破支撑后反抽未站回，量能验证"""
    support = snap["snap_support"]
    snap_close = snap["snap_price"]
    if close > support * 1.02 and volume > snap["snap_volume"] * 0.8:
        return "expired", f"站回支撑 {support:.2f}，FTI 失败"
    if close <= snap["snap_support"] * 0.98 and high < support:
        return "confirmed", f"跌破支撑 {support:.2f}，反抽无力确认"
    if days >= 2 and close < support:
        return "confirmed", f"连续 {days}天在支撑 {support:.2f} 下方，确认"
    return "pending", "等待跌破支撑"


def _check_sow(snap: Dict, high: float, close: float, volume: float, days: int) -> Tuple[str, str]:
    """SOW 确认：下跌放量后的弱势反弹"""
    snap_low = snap["snap_low"]
    snap_close = snap["snap_price"]
    if close > snap_close * 1.02:
        return "expired", f"收回信号日高点 {snap_close:.2f}，SOW 失效"
    if close <= snap_low:
        return "confirmed", f"跌破信号日低点 {snap_low:.2f}，弱势确认"
    if days >= 2 and close < snap_close:
        return "expired", f"{days}天内未有效创出新低"
    return "pending", "等待创出新低"


# ============================================================================
# 孟洪涛原则：信号衰减函数
# ============================================================================

def calculate_signal_decay(
    signal_type: str,
    signal_date: datetime,
    current_date: datetime = None,
    initial_quality: float = 1.0
) -> Dict:
    """
    计算信号衰减后的质量评分（孟洪涛原则）

    孟洪涛理论强调：
    - 信号质量会随着时间推移而衰减
    - 使用指数衰减模型，类似于放射性衰变
    - 不同类型信号有不同的半衰期

    Args:
        signal_type: 信号类型 (spring, joc, sos, etc.)
        signal_date: 信号产生日期
        current_date: 当前日期（默认为今天）
        initial_quality: 初始质量评分 (0-1)

    Returns:
        {
            'decay_factor': float,      # 衰减系数 (0-1)
            'current_quality': float,    # 当前质量评分 (0-1)
            'days_elapsed': int,         # 经过天数
            'is_expired': bool,          # 是否已失效
            'status': str,               # 状态描述
        }
    """
    if current_date is None:
        current_date = datetime.now()

    # 计算经过的天数
    days_elapsed = (current_date - signal_date).days
    if days_elapsed < 0:
        days_elapsed = 0

    # 获取信号衰减配置
    config = SIGNAL_DECAY_CONFIG.get(signal_type, {
        "half_life": 5,
        "max_decay": 0.3,
        "critical_days": 7,
    })

    half_life = config["half_life"]
    max_decay = config["max_decay"]
    critical_days = config["critical_days"]

    # 计算衰减系数：使用指数衰减公式
    # decay_factor = e^(-0.693 * days / half_life)
    # 其中 -0.693 = -ln(2)，确保经过一个半衰期后质量变为原来的 50%
    decay_factor = math.exp(-0.693 * days_elapsed / half_life)

    # 应用最小保留比例
    decay_factor = max(decay_factor, max_decay)

    # 计算当前质量
    current_quality = initial_quality * decay_factor

    # 判断是否已失效
    is_expired = days_elapsed > critical_days

    # 状态描述
    if days_elapsed == 0:
        status = "fresh"
        status_desc = "信号刚产生，处于最佳状态"
    elif days_elapsed <= half_life:
        status = "good"
        status_desc = f"信号保持良好（经过{days_elapsed}天，衰减{decay_factor:.0%}）"
    elif days_elapsed <= critical_days:
        status = "decaying"
        status_desc = f"信号正在衰减（经过{days_elapsed}天，衰减{decay_factor:.0%}）"
    else:
        status = "expired"
        status_desc = f"信号已失效（经过{days_elapsed}天，超过临界值{critical_days}天）"

    return {
        'decay_factor': round(decay_factor, 3),
        'current_quality': round(current_quality, 3),
        'days_elapsed': days_elapsed,
        'is_expired': is_expired,
        'status': status,
        'description': status_desc,
    }


def apply_decay_to_signal_quality(
    signal_type: str,
    signal_date: datetime,
    original_score: float,
    current_date: datetime = None
) -> float:
    """
    将信号衰减应用到原始评分上（孟洪涛原则）

    Args:
        signal_type: 信号类型
        signal_date: 信号产生日期
        original_score: 原始评分 (0-100)
        current_date: 当前日期

    Returns:
        应用衰减后的评分 (0-100)
    """
    decay_info = calculate_signal_decay(signal_type, signal_date, current_date)

    # 如果信号已失效，返回最低分
    if decay_info['is_expired']:
        return max(0, original_score * decay_info['decay_factor'])

    # 否则按衰减系数调整
    decayed_score = original_score * decay_info['decay_factor']
    return max(0, min(100, decayed_score))


def get_signal_age_score(signal_type: str, days_elapsed: int) -> float:
    """
    根据信号年龄快速计算衰减评分（孟洪涛原则）

    用于快速判断信号是否仍然有效

    Returns:
        衰减系数 (0-1)，0 表示完全失效，1 表示完全有效
    """
    config = SIGNAL_DECAY_CONFIG.get(signal_type, {
        "half_life": 5,
        "max_decay": 0.3,
        "critical_days": 7,
    })

    half_life = config["half_life"]
    max_decay = config["max_decay"]

    decay_factor = math.exp(-0.693 * days_elapsed / half_life)
    decay_factor = max(decay_factor, max_decay)

    return round(decay_factor, 3)
