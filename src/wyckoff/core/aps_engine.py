import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class APSEngine:
    """
    威科夫筹码持续吸收动力学引擎 (Absorption Persistence Score Engine - APS) - WIE 3.0 MVP
    
    抛弃简单单日统计，采用时间衰减记忆与象限状态依赖加权 (Regime-aware)。
    计算公式: APS_t = sum_{i=0}^N exp(-lambda * dt_i) * EvR_{t-i} * omega_regime(t-i)
    """

    def __init__(self, memory_window: int = 60, half_life: float = 10.0):
        self.window = memory_window
        # lambda = ln(2) / half_life
        self.decay_lambda = np.log(2.0) / half_life

    def analyze(self, df: pd.DataFrame, evr_col: str = 'evr_divergence', atr_col: str = 'atr_ratio') -> pd.DataFrame:
        """
        计算状态依赖的持续吸收评分
        :param df: 必须先通过 VSAAnalyzer 和 ExpansionEfficiency 产生 evr_col 和 atr_col
        """
        if evr_col not in df.columns:
            raise ValueError(f"缺少必要列: {evr_col}，请先执行 VSA解构")

        out_df = df.copy()

        # 1. 确定 Regime Weight (omega_regime)
        # 如果 atr_col 存在，通过 ATR 的历史相对高低判定波动率状态
        if atr_col in out_df.columns:
            atr_mean = out_df[atr_col].rolling(window=self.window, min_periods=1).mean()
            atr_std = out_df[atr_col].rolling(window=self.window, min_periods=1).std().fillna(1e-5)
            atr_z = (out_df[atr_col] - atr_mean) / atr_std.replace(0, np.nan).fillna(1e-5)
            
            # Regime 判定规则：
            # 极低波动磨底带 (atr_z < -0.8): omega = 1.8 (机构极其偏爱，含金量极高)
            # 极高波动恐慌带 (atr_z > 1.2): omega = 0.7 (多空惨烈交换，噪音多)
            # 中性带: omega = 1.0
            def get_omega(z: float) -> float:
                if z < -0.8:
                    return 1.8
                elif z > 1.2:
                    return 0.7
                else:
                    return 1.0

            omega_s = atr_z.apply(get_omega)
        else:
            omega_s = pd.Series(1.0, index=out_df.index)

        out_df['regime_weight'] = omega_s

        # 2. 计算具备时间衰减与状态权重的单期吸收动量
        out_df['weighted_evr'] = out_df[evr_col] * out_df['regime_weight']

        # 3. 滚动时间衰减记忆累加计算 APS
        aps_values = []
        n_rows = len(out_df)
        
        # 预先计算衰减因子数组 (从0到 window-1 的衰减)
        decay_weights = np.exp(-self.decay_lambda * np.arange(self.window))

        weighted_evr_arr = np.asarray(out_df['weighted_evr'])

        for i in range(n_rows):
            start_idx = max(0, i - self.window + 1)
            # 截取历史序列
            sub_arr = weighted_evr_arr[start_idx : i + 1]
            sub_len = len(sub_arr)
            # 对应的衰减因子 (近期的 i 对应 dt=0)
            weights_sub = decay_weights[:sub_len][::-1]  # 倒序，最后一个元素权重最大(1.0)
            
            aps_val = np.sum(sub_arr * weights_sub)
            aps_values.append(aps_val)

        out_df['aps'] = aps_values

        # 4. 计算 APS 动量 (APS Persistence)
        out_df['aps_sma5'] = out_df['aps'].rolling(window=5, min_periods=1).mean()
        out_df['aps_momentum'] = out_df['aps'] - out_df['aps_sma5']

        return out_df

    def extract_summary(self, out_df: pd.DataFrame) -> Dict[str, Any]:
        if out_df.empty:
            return {}
        last = out_df.iloc[-1]
        
        is_strong_accumulation = last['aps'] > 15.0 and last['aps_momentum'] > 0
        
        return {
            'regime_weight': float(last['regime_weight']),
            'aps': float(last['aps']),
            'aps_sma5': float(last['aps_sma5']),
            'aps_momentum': float(last['aps_momentum']),
            'is_strong_accumulation': bool(is_strong_accumulation)
        }
