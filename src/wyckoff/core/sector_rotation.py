"""
板块轮动状态分类

基于行业指数 MA 排列和收益动量，判断行业处于哪个阶段。
"""
from typing import Dict, Optional, Any
import pandas as pd

SECTOR_STATES = {
    "HEALTHY_MAINLINE": "主线健康推进",
    "CONSENSUS_CLIMAX": "连续一致高潮",
    "DISAGREEMENT_PULLBACK": "主流分歧回撤",
    "DISTRIBUTION_RISK": "退潮派发风险",
    "NEUTRAL_MIXED": "中性混沌",
}

STATE_GUIDANCE = {
    "HEALTHY_MAINLINE": "板块主线健康推进，可正常参与",
    "CONSENSUS_CLIMAX": "板块连续高潮，不宜追高，等分歧",
    "DISAGREEMENT_PULLBACK": "板块分歧回撤，寻找 Spring/LPS 低吸机会",
    "DISTRIBUTION_RISK": "板块退潮派发，除极强个股外应避开",
    "NEUTRAL_MIXED": "板块状态混沌，个股结构优先",
}


def classify_sector_state(
    sector_data: pd.DataFrame,
    name: str = "",
) -> Dict[str, Any]:
    """
    基于行业指数数据判断板块状态。
    
    判断逻辑：
    1. MA20 > MA50 > MA200 + 近 5 日涨幅 > 5% → CONSENSUS_CLIMAX
    2. MA20 > MA50 > MA200 + 涨幅适中 → HEALTHY_MAINLINE
    3. MA20 < MA50 但 MA50 > MA200 → DISAGREEMENT_PULLBACK
    4. MA50 < MA200 + 近 5 日下跌 → DISTRIBUTION_RISK
    5. 其余 → NEUTRAL_MIXED
    """
    if sector_data is None or len(sector_data) < 60:
        return {"state": "NEUTRAL_MIXED", "label": "数据不足", "guidance": STATE_GUIDANCE["NEUTRAL_MIXED"]}

    close = sector_data['Close']
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]
    ma200 = close.rolling(200).mean().iloc[-1]
    last_close = close.iloc[-1]

    if pd.isna(ma20) or pd.isna(ma50):
        return {"state": "NEUTRAL_MIXED", "label": SECTOR_STATES["NEUTRAL_MIXED"], "guidance": STATE_GUIDANCE["NEUTRAL_MIXED"]}

    # 近期收益
    ret_5d = (last_close / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0
    ret_20d = (last_close / close.iloc[-21] - 1) * 100 if len(close) > 20 else 0

    if pd.notna(ma200):
        if ma20 > ma50 > ma200 and last_close > ma20:
            if ret_5d > 5:
                state = "CONSENSUS_CLIMAX"
            else:
                state = "HEALTHY_MAINLINE"
        elif ma20 < ma50 < ma200 and last_close < ma20:
            state = "DISTRIBUTION_RISK"
        elif ma20 < ma50:
            state = "DISAGREEMENT_PULLBACK"
        else:
            state = "NEUTRAL_MIXED"
    else:
        state = "NEUTRAL_MIXED"

    return {
        "state": state,
        "label": SECTOR_STATES.get(state, "未知"),
        "guidance": STATE_GUIDANCE.get(state, ""),
        "name": name,
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "ret_5d_pct": round(ret_5d, 2),
        "ret_20d_pct": round(ret_20d, 2),
    }
