"""
信号生命周期管理：pending → confirmed / expired

每个信号触发时拍快照，后续逐日检查是否被确认或失效。
"""
from typing import Dict, Optional, Tuple

from types import MappingProxyType

SIGNAL_TTL: Dict[str, int] = MappingProxyType({
    "spring": 3,
    "sos": 2,
    "lps": 3,
    "lpsy": 3,
    "joc": 2,
    "fti": 2,
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
