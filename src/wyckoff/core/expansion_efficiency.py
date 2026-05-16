import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class ExpansionEfficiencyEngine:
    """
    威科夫供给真空推动效率引擎 (Expansion Efficiency Engine) - WIE 3.0 MVP
    
    彻底消除极度缩量除零奇点，采用对数收益率动量标准化与相对成交量 (RVOL)。
    核心特征输出：
    1. RVOL (Relative Volume): 相对成交量比率
    2. Expansion Efficiency: 单位相对流动性推动对数位移比率
    3. Efficiency Momentum: 突破推动效率的连续改善动量
    """
    
    def __init__(self, rvol_window: int = 20, return_window: int = 1, eps: float = 1e-5):
        self.rvol_window = rvol_window
        self.return_window = return_window
        self.eps = eps

    def analyze(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        对输入的 DataFrame 计算动量相对化修正推动效率
        :param df: 包含 ['high', 'low', 'close', 'volume'] (支持大小写)
        :return: 增加特征列的 DataFrame
        """
        # 标准化列名 (支持大小写混合)
        out_df = df.copy()
        col_mapping = {}

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

        # 1. 计算对数收益率 (Price Momentum)
        # return_t = ln(close_t / close_{t-N})
        out_df['log_return'] = np.log(out_df['close'] / out_df['close'].shift(self.return_window))
        out_df['log_return'] = out_df['log_return'].fillna(0.0)

        # 2. 计算相对成交量 RVOL (Relative Volume)
        # RVOL_t = volume_t / SMA(volume, 20)
        vol_sma = out_df['volume'].rolling(window=self.rvol_window, min_periods=1).mean()
        rvol = out_df['volume'] / vol_sma.replace(0, np.nan)
        out_df['rvol'] = rvol.fillna(1.0)

        # 3. 计算 ATR_20 Standardized Displacement
        tr1 = out_df['high'] - out_df['low']
        tr2 = (out_df['high'] - out_df['close'].shift(1)).abs()
        tr3 = (out_df['low'] - out_df['close'].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr20 = tr.rolling(window=self.rvol_window, min_periods=1).mean().replace(0, np.nan).fillna(1e-5)
        out_df['atr_ratio'] = atr20 / out_df['close']

        # 4. 动量相对化修正推动公式 (消除奇点)
        # Efficiency_t = (log_return / atr_ratio) / (RVOL + eps)
        # 既消除了标的绝对基数差异，也杜绝了极度缩量除 0 奇点
        normalized_return = out_df['log_return'] / out_df['atr_ratio']
        out_df['expansion_efficiency'] = normalized_return / (out_df['rvol'] + self.eps)

        # 5. 追踪推动效率连续演进曲线 (Efficiency Momentum)
        # 计算过去 5 个周期正向推动效率的斜率或移动均值
        out_df['efficiency_sma5'] = out_df['expansion_efficiency'].rolling(window=5, min_periods=1).mean()
        out_df['efficiency_improvement'] = out_df['efficiency_sma5'] - out_df['efficiency_sma5'].shift(5)

        return out_df

    def extract_summary(self, out_df: pd.DataFrame) -> Dict[str, Any]:
        """
        提取最新一条记录的推动效率摘要
        """
        if out_df.empty:
            return {}
        last = out_df.iloc[-1]
        
        is_supply_vacuum_breakout = (last['expansion_efficiency'] > 2.0) and (last['log_return'] > 0.02)
        
        return {
            'rvol': float(last['rvol']),
            'expansion_efficiency': float(last['expansion_efficiency']),
            'efficiency_sma5': float(last['efficiency_sma5']),
            'efficiency_improvement': float(last['efficiency_improvement']),
            'is_supply_vacuum_breakout': bool(is_supply_vacuum_breakout)
        }
