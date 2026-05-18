"""
A股市场特殊处理工具类

威科夫理论在A股市场的应用需要考虑涨跌停限制的特殊情况：
- 主板：10% 涨跌停
- 创业板/科创板：20% 涨跌停
- 北交所：30% 涨跌停
- ST股：10% 涨跌停（2026年全面注册制新规）

涨跌停时的成交量特征：
- 涨停：低量 ≠ 弱需求，而是供应极度枯竭（强势信号）
- 跌停：低量 ≠ 弱供应，而是需求枯竭（可能预示反弹）
"""

import pandas as pd
from typing import Dict

# A股涨跌停相关常量
LIMIT_TOLERANCE = 0.99           # 涨跌停判断容差（99%）
SEALED_TOLERANCE = 0.005         # 封板判断容差（0.5%）
VOLUME_RATIO_EXTREME_LOW = 0.7   # 极低量能阈值
VOLUME_RATIO_LOW = 1.0           # 低量能阈值
BOARD_CODE_PREFIXES = {
    'chi_next': ['SZ.300', '300'],      # 创业板
    'star': ['SH.688', '688'],           # 科创板
    'bse': ['BJ.', '8', '4']             # 北交所
}


class ChinaMarketHelper:
    """A股市场特殊处理工具类"""

    # A股涨跌停限制
    LIMIT_MAIN_BOARD = 0.10       # 主板 10%
    LIMIT_CHI_NEXT = 0.20         # 创业板/科创板 20%
    LIMIT_BSE = 0.30              # 北交所 30%
    LIMIT_ST = 0.10               # ST股 10%

    @staticmethod
    def detect_limit_status(row: pd.Series, prev_close: float = None) -> Dict:
        """
        检测是否为涨跌停

        Args:
            row: 包含 OHLCV 数据的 Series
            prev_close: 前一日收盘价（用于计算涨跌幅）

        Returns:
            包含涨跌停状态的字典
        """
        if prev_close is None:
            # 尝试从 row 中获取 prev_close，否则使用当前收盘价
            prev_close = row.get('prev_close', row['Close'])

        if prev_close <= 0:
            return {"is_limit": False, "type": None}

        change_pct = (row['Close'] - prev_close) / prev_close

        # 涨停判断（考虑不同板块的涨跌幅限制）
        is_limit_up = (
            change_pct >= ChinaMarketHelper.LIMIT_MAIN_BOARD * LIMIT_TOLERANCE or
            change_pct >= ChinaMarketHelper.LIMIT_CHI_NEXT * LIMIT_TOLERANCE or
            change_pct >= ChinaMarketHelper.LIMIT_BSE * LIMIT_TOLERANCE
        )

        # 跌停判断
        is_limit_down = (
            change_pct <= -ChinaMarketHelper.LIMIT_MAIN_BOARD * LIMIT_TOLERANCE or
            change_pct <= -ChinaMarketHelper.LIMIT_CHI_NEXT * LIMIT_TOLERANCE or
            change_pct <= -ChinaMarketHelper.LIMIT_BSE * LIMIT_TOLERANCE
        )

        if is_limit_up:
            # 检查是否封板（收盘价 = 最高价）
            is_sealed = abs(row['Close'] - row['High']) / prev_close < SEALED_TOLERANCE
            return {
                "is_limit": True,
                "type": "limit_up",
                "is_sealed": is_sealed,
                "change_pct": round(change_pct * 100, 2),
                "interpretation": "涨停" if is_sealed else "冲击涨停"
            }
        elif is_limit_down:
            # 检查是否封板（收盘价 = 最低价）
            is_sealed = abs(row['Close'] - row['Low']) / prev_close < SEALED_TOLERANCE
            return {
                "is_limit": True,
                "type": "limit_down",
                "is_sealed": is_sealed,
                "change_pct": round(change_pct * 100, 2),
                "interpretation": "跌停" if is_sealed else "冲击跌停"
            }

        return {"is_limit": False, "type": None}

    @staticmethod
    def adjust_volume_interpretation(
        volume_ratio: float,
        price_action: str,
        limit_status: Dict
    ) -> Dict:
        """
        根据涨跌停状态调整成交量解读

        威科夫理论规则：
        - 涨停时低量 ≠ 弱需求，而是供应极度枯竭（强势信号）
        - 跌停时低量 ≠ 弱供应，而是需求枯竭（可能预示反弹）

        Args:
            volume_ratio: 成交量比率
            price_action: 价格行为 ('up', 'down', 'flat')
            limit_status: 涨跌停状态字典

        Returns:
            调整后的成交量解读
        """
        if not limit_status.get("is_limit"):
            return {
                "original_ratio": volume_ratio,
                "adjusted_interpretation": "normal",
                "note": ""
            }

        is_limit_up = limit_status.get("type") == "limit_up"
        is_sealed = limit_status.get("is_sealed", False)

        if is_limit_up and is_sealed:
            # 封板涨停：低量是极度强势信号
            if volume_ratio < VOLUME_RATIO_EXTREME_LOW:
                return {
                    "original_ratio": volume_ratio,
                    "adjusted_interpretation": "EXTREME_SUPPLY_EXHAUSTION",
                    "note": "⚠️ A股涨停封板：低量=供应极度枯竭，威科夫理论中的'无供应'状态，强势信号"
                }
            elif volume_ratio < VOLUME_RATIO_LOW:
                return {
                    "original_ratio": volume_ratio,
                    "adjusted_interpretation": "SUPPLY_EXHAUSTION",
                    "note": "⚠️ A股涨停：缩量=供应不足，符合强势特征"
                }

        elif limit_status.get("type") == "limit_down" and is_sealed:
            # 封板跌停：低量可能预示反弹
            if volume_ratio < VOLUME_RATIO_EXTREME_LOW:
                return {
                    "original_ratio": volume_ratio,
                    "adjusted_interpretation": "DEMAND_EXHAUSTION_MAY_REBOUND",
                    "note": "⚠️ A股跌停封板：低量=需求枯竭，可能预示反弹（需结合Spring信号）"
                }

        return {
            "original_ratio": volume_ratio,
            "adjusted_interpretation": "normal",
            "note": ""
        }

    @staticmethod
    def get_board_limit(symbol: str) -> float:
        """
        根据股票代码获取涨跌停限制

        Args:
            symbol: 股票代码（如 'sh.600519', 'sz.300001'）

        Returns:
            涨跌停限制（百分比，如 0.10 表示 10%）
        """
        if not symbol:
            return ChinaMarketHelper.LIMIT_MAIN_BOARD

        symbol_upper = symbol.upper()

        # 检查是否为ST股
        if 'ST' in symbol_upper:
            return ChinaMarketHelper.LIMIT_ST

        # 创业板 (300xxx)
        if any(prefix in symbol_upper for prefix in BOARD_CODE_PREFIXES['chi_next']):
            return ChinaMarketHelper.LIMIT_CHI_NEXT

        # 科创板 (688xxx)
        if any(prefix in symbol_upper for prefix in BOARD_CODE_PREFIXES['star']):
            return ChinaMarketHelper.LIMIT_CHI_NEXT

        # 北交所 (8xxxxx, 4xxxxx)
        if any(prefix in symbol_upper for prefix in BOARD_CODE_PREFIXES['bse']) or \
           symbol.startswith(('8', '4')):
            return ChinaMarketHelper.LIMIT_BSE

        # 默认主板
        return ChinaMarketHelper.LIMIT_MAIN_BOARD

    @staticmethod
    def should_ignore_weak_volume_signal(
        current_row: pd.Series,
        prev_close: float,
        volume_ratio: float
    ) -> tuple:
        """
        判断是否应该忽略弱势量能信号（因为可能是涨跌停导致的）

        Args:
            current_row: 当前K线数据
            prev_close: 前一日收盘价
            volume_ratio: 成交量比率

        Returns:
            (should_ignore, reason)
        """
        limit_status = ChinaMarketHelper.detect_limit_status(current_row, prev_close)

        if limit_status["is_limit"]:
            if limit_status["type"] == "limit_up" and volume_ratio < VOLUME_RATIO_LOW:
                return True, "涨停低量是供应枯竭信号，不是弱势"
            elif limit_status["type"] == "limit_down" and volume_ratio < VOLUME_RATIO_LOW:
                return True, "跌停低量是需求枯竭信号，不表示供应强势"

        return False, ""
