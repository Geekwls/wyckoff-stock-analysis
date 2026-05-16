import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class VSAAnalyzer:
    """
    威科夫微观量价展开分析引擎 (Microstructure VSA Engine) - WIE 3.0 MVP
    
    消除固定阈值失真，采用完全自适应的动态统计归一化模型。
    核心特征输出：
    1. Spread Z-Score: 波幅相对历史分位
    2. Vol_Percentile_252: 成交量在过去1年的百分位
    3. EvR_Divergence: 单点量价效率差值 (Effort vs Result)
    4. CLV: 日内吃单扫单效率 (Close Location Value)
    """
    
    def __init__(self, spread_window: int = 60, vol_percentile_window: int = 252):
        self.spread_window = spread_window
        self.vol_window = vol_percentile_window

    def analyze(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        对输入的 DataFrame 执行微观量价归一化解构分析
        :param df: 必须包含 ['high', 'low', 'close', 'volume'] 的 DataFrame (支持大小写)
        :return: 增加归一化特征列的 DataFrame
        """
        # 标准化列名 (支持大小写混合)
        out_df = df.copy()
        col_mapping = {}

        # 创建列名映射字典
        for col in out_df.columns:
            col_lower = col.lower()
            if col_lower in ['high', 'low', 'close', 'volume', 'open']:
                col_mapping[col] = col_lower

        if col_mapping:
            out_df = out_df.rename(columns=col_mapping)

        required_cols = ['high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in out_df.columns:
                raise ValueError(f"输入数据缺失必要字段: {col} (可用列: {out_df.columns.tolist()})")

        # 1. 计算 Spread
        out_df['spread'] = out_df['high'] - out_df['low']
        
        # 2. 计算 Spread Z-Score
        r_mean = out_df['spread'].rolling(window=self.spread_window, min_periods=1).mean()
        r_std = out_df['spread'].rolling(window=self.spread_window, min_periods=1).std()
        # 避免除零
        r_std = r_std.replace(0, np.nan).fillna(1e-5)
        out_df['spread_zscore'] = (out_df['spread'] - r_mean) / r_std

        # 3. 计算 Volume Percentile 252 (0.0 到 1.0)
        def calc_percentile(s: pd.Series) -> float:
            if len(s) == 0:
                return 0.0
            last_val = s.iloc[-1]
            return float((s < last_val).sum() / len(s))

        out_df['vol_percentile'] = out_df['volume'].rolling(window=self.vol_window, min_periods=1).apply(
            calc_percentile, raw=False
        )

        # 4. 计算 Spread Percentile 252 供 EvR 差值使用
        out_df['spread_percentile'] = out_df['spread'].rolling(window=self.vol_window, min_periods=1).apply(
            calc_percentile, raw=False
        )

        # 5. 单点量价效率差值 (Effort vs Result - EvR)
        # EvR 越大，说明量能极大 (Effort大) 但实际涨跌波幅极小 (Result小)，典型的主力暗中吸收或派发滞涨
        out_df['evr_divergence'] = out_df['vol_percentile'] - out_df['spread_percentile']

        # 6. 计算日内吃单扫单效率测度 (Close Location Value - CLV)
        # CLV = ((close - low) - (high - close)) / (high - low)
        denom = out_df['high'] - out_df['low']
        clv_raw = ((out_df['close'] - out_df['low']) - (out_df['high'] - out_df['close'])) / denom.replace(0, np.nan)
        out_df['clv'] = clv_raw.fillna(0.0)

        return out_df

    def extract_latest_vsa_summary(self, out_df: pd.DataFrame) -> Dict[str, Any]:
        """
        提取最新一条 K 线的专家级微观结构摘要
        """
        if out_df.empty:
            return {}
        last = out_df.iloc[-1]
        
        # 判定微观特征
        is_hidden_absorption = (last['evr_divergence'] > 0.5) and (last['clv'] > 0.3)
        is_supply_dominance = (last['spread_zscore'] > 1.5) and (last['clv'] < -0.7) and (last['vol_percentile'] > 0.8)
        
        return {
            'spread_zscore': float(last['spread_zscore']),
            'vol_percentile': float(last['vol_percentile']),
            'spread_percentile': float(last['spread_percentile']),
            'evr_divergence': float(last['evr_divergence']),
            'clv': float(last['clv']),
            'is_hidden_absorption': bool(is_hidden_absorption),
            'is_supply_dominance': bool(is_supply_dominance),
            'timestamp': str(out_df.index[-1] if isinstance(out_df.index, pd.DatetimeIndex) else len(out_df))
        }
