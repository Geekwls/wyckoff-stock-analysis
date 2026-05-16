import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple

class RegimeTracker:
    """
    威科夫波动率状态追踪与筹码控制峰引擎 (Regime Tracker & VPOC Engine) - WIE 3.0 MVP
    
    实现换手收敛记忆 (CDS)、死票参与度甄别 (LCS)、瞬态震仓雷达 [Flag: Spring] 以及 VPOC 穿越铁律。
    """
    
    def __init__(self, regime_window: int = 60, vpoc_bins: int = 50):
        self.window = regime_window
        self.bins = vpoc_bins

    def calculate_vpoc(self, df: pd.DataFrame, start_idx: int, end_idx: int) -> float:
        """
        计算特定 K 线范围内的成交量控制峰值点 (Volume Point of Control - VPOC)
        """
        sub_df = df.iloc[start_idx : end_idx + 1]
        if sub_df.empty or sub_df['high'].max() == sub_df['low'].min():
            return float(df['close'].iloc[-1])

        min_px = sub_df['low'].min()
        max_px = sub_df['high'].max()
        
        # 创建价格箱体边界
        bin_edges = np.linspace(min_px, max_px, self.bins + 1)
        bin_centers = 0.5 * (bin_edges[1:] + bin_edges[:-1])
        vol_profile = np.zeros(self.bins)

        for _, row in sub_df.iterrows():
            h, l, v = row['high'], row['low'], row['volume']
            if h == l:
                continue
            # 找到落入的箱体索引
            idx_start = np.searchsorted(bin_edges, l, side='left')
            idx_end = np.searchsorted(bin_edges, h, side='right')
            idx_start = max(0, min(idx_start, self.bins - 1))
            idx_end = max(1, min(idx_end, self.bins))
            
            span = idx_end - idx_start
            if span > 0:
                vol_per_bin = v / span
                vol_profile[idx_start : idx_end] += vol_per_bin

        # 找到成交量最大的价格箱体中心
        max_bin_idx = int(np.argmax(vol_profile))
        return float(bin_centers[max_bin_idx])

    def track(self, df: pd.DataFrame, vsa_df: pd.DataFrame, aps_df: pd.DataFrame) -> pd.DataFrame:
        """
        执行收敛状态、死票甄别、破底翻触发器追踪
        :param df: 原始带高低收量数据 (支持大小写列名)
        :param vsa_df: 包含 ['clv', 'evr_divergence', 'atr_ratio'] 等特征的 df
        :param aps_df: 包含 ['aps'] 的 df
        """
        # 标准化列名
        out_df = df.copy()
        col_mapping = {}

        for col in out_df.columns:
            col_lower = col.lower()
            if col_lower in ['high', 'low', 'close', 'volume', 'open']:
                col_mapping[col] = col_lower

        if col_mapping:
            out_df = out_df.rename(columns=col_mapping)
        for col in ['clv', 'evr_divergence', 'atr_ratio']:
            if col in vsa_df.columns:
                out_df[col] = vsa_df[col]
        if 'aps' in aps_df.columns:
            out_df['aps'] = aps_df['aps']
        if 'expansion_efficiency' in vsa_df.columns:
            out_df['expansion_efficiency'] = vsa_df['expansion_efficiency']
        elif 'expansion_efficiency' in aps_df.columns:
            out_df['expansion_efficiency'] = aps_df['expansion_efficiency']

        # 1. 判定 Low Vol Regime (象限 II 磨底期)
        if 'atr_ratio' in out_df.columns:
            atr_mean = out_df['atr_ratio'].rolling(window=self.window, min_periods=1).mean()
            out_df['is_low_vol'] = (out_df['atr_ratio'] < atr_mean * 0.95)
        else:
            out_df['is_low_vol'] = True

        # 2. 计算 CDS (Compression Duration Score)
        # 统计在最近 60 周期内连续或总共处于 low_vol 的累积天数
        cds_vals = []
        curr_cds = 0
        for val in out_df['is_low_vol'].values:
            if val:
                curr_cds += 1
            else:
                curr_cds = max(0, curr_cds - 1)
            cds_vals.append(curr_cds)
        out_df['cds'] = cds_vals

        # 3. 计算 LCS (Liquidity Compression Score) 甄别死票
        # LCS = Normalized_Turnover * Volume_Persistence * CLV_Consistency
        # 如果量极缩但一直有人护盘(CLV长期>0)说明是健康收敛；否则全是无成交垃圾死票
        vol_mean = out_df['volume'].rolling(window=self.window, min_periods=1).mean()
        norm_turnover = (out_df['volume'] / vol_mean.replace(0, np.nan)).fillna(1.0)
        # 计算过去 10 周期 CLV > 0 的占比
        clv_pos_ratio = (out_df['clv'] > 0).rolling(window=10, min_periods=1).mean()
        
        out_df['lcs'] = norm_turnover * clv_pos_ratio * 10.0

        # 4. 实时后台测算 VPOC 筹码控制峰
        vpoc_vals = []
        n_rows = len(out_df)
        for i in range(n_rows):
            start_idx = max(0, i - self.window + 1)
            vp_val = self.calculate_vpoc(out_df, start_idx, i)
            vpoc_vals.append(vp_val)
        out_df['vpoc_price'] = vpoc_vals

        # 5. 瞬态破底翻事件雷达 (Transient Spring / Trap Event Flag)
        # 触发条件: 处于 S2 磨底带 (CDS > 10)，突发单日暴跌 (如 close 跌幅 > 3%)
        # 但筹码吸收分 APS 与日内吃单 CLV 不降反升
        log_ret = np.log(out_df['close'] / out_df['close'].shift(1)).fillna(0.0)
        aps_diff = out_df['aps'] - out_df['aps'].shift(1).fillna(0.0)
        
        spring_flags = []
        for i in range(n_rows):
            row = out_df.iloc[i]
            ret_t = log_ret.iloc[i]
            d_aps = aps_diff.iloc[i]
            cds_t = row['cds']
            clv_t = row['clv']
            
            # 制造恐慌下杀 (ret < -0.025)，但蓄势底座足够 (cds > 10) 且后台主力大单狂扫 (d_aps > 0 且 clv > 0.4)
            if cds_t > 10 and ret_t < -0.025 and d_aps > 0 and clv_t > 0.4:
                spring_flags.append('FLAG: SPRING / TRAP')
            else:
                spring_flags.append('NORMAL')
                
        out_df['event_flag'] = spring_flags

        # 6. S3 确立验证条件 (VPOC 穿越铁律)
        # S3 (需求萌芽) 确立标准: close 必须带量企稳于 vpoc_price 之上，且推动效率高
        if 'expansion_efficiency' in out_df.columns:
            out_df['is_s3_confirmed'] = (out_df['close'] > out_df['vpoc_price']) & (out_df['expansion_efficiency'] > 1.2)
        else:
            out_df['is_s3_confirmed'] = (out_df['close'] > out_df['vpoc_price'])

        return out_df

    def extract_summary(self, out_df: pd.DataFrame) -> Dict[str, Any]:
        if out_df.empty:
            return {}
        last = out_df.iloc[-1]
        
        return {
            'cds': int(last['cds']),
            'lcs': float(last['lcs']),
            'vpoc_price': float(last['vpoc_price']),
            'event_flag': str(last['event_flag']),
            'is_s3_confirmed': bool(last['is_s3_confirmed'])
        }
