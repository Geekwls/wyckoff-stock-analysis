import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

class RelativeStrengthEngine:
    """
    威科夫跨资产资本流动向与相对流动性留存引擎 (Relative Strength & Liquidity Retention Engine) - WIE 3.0 MVP
    
    剔除伪强 RS 噪音，计算大盘恐慌杀跌时的流动性留存比率，精确甄别主力锁仓底仓足迹。
    核心特征输出：
    1. Liquidity Retention Ratio: 相对大盘流动性留存率
    2. Hidden Strength: 主力拒绝交出筹码暗藏强势信号
    3. Hidden Weakness: 高位放量滞涨资金暗退信号
    """

    def __init__(self, window: int = 20):
        self.window = window

    def analyze(self, asset_df: pd.DataFrame, index_df: pd.DataFrame) -> pd.DataFrame:
        """
        跨资产相对流动性解构分析
        :param asset_df: 个股数据 (支持大小写列名)
        :param index_df: 对齐的基准大盘数据 (如上证指数)
        """
        # 标准化列名
        def normalize_cols(df):
            df_norm = df.copy()
            col_mapping = {}
            for col in df.columns:
                col_lower = col.lower()
                if col_lower in ['high', 'low', 'close', 'volume', 'open']:
                    col_mapping[col] = col_lower
            if col_mapping:
                df_norm = df_norm.rename(columns=col_mapping)
            return df_norm

        asset_df = normalize_cols(asset_df)
        index_df = normalize_cols(index_df)

        required_cols = ['high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in asset_df.columns or col not in index_df.columns:
                raise ValueError(f"输入数据缺失必要字段: {col} (asset列: {asset_df.columns.tolist()}, index列: {index_df.columns.tolist()})")

        out_df = asset_df.copy()

        # 1. 对齐数据 (基于索引对齐)
        # 为确保安全性，提取公共时间轴
        common_idx = out_df.index.intersection(index_df.index)
        if len(common_idx) == 0:
            # 如果不是时间戳索引，假设按行顺序对应
            idx_sub = index_df.iloc[-len(out_df):].reset_index(drop=True)
            out_df['idx_close'] = idx_sub['close'].values
            out_df['idx_vol'] = idx_sub['volume'].values
            out_df['idx_high'] = idx_sub['high'].values
            out_df['idx_low'] = idx_sub['low'].values
        else:
            out_df['idx_close'] = index_df.loc[common_idx, 'close']
            out_df['idx_vol'] = index_df.loc[common_idx, 'volume']
            out_df['idx_high'] = index_df.loc[common_idx, 'high']
            out_df['idx_low'] = index_df.loc[common_idx, 'low']

        out_df = out_df.ffill().bfill()

        # 2. 计算大盘与个股的对数收益率
        out_df['idx_log_return'] = np.log(out_df['idx_close'] / out_df['idx_close'].shift(1)).fillna(0.0)
        out_df['asset_log_return'] = np.log(out_df['close'] / out_df['close'].shift(1)).fillna(0.0)

        # 3. 计算相对成交量活跃度 RVOL
        asset_vol_sma = out_df['volume'].rolling(window=self.window, min_periods=1).mean().replace(0, np.nan)
        out_df['asset_rvol'] = (out_df['volume'] / asset_vol_sma).fillna(1.0)
        
        idx_vol_sma = out_df['idx_vol'].rolling(window=self.window, min_periods=1).mean().replace(0, np.nan)
        out_df['idx_rvol'] = (out_df['idx_vol'] / idx_vol_sma).fillna(1.0)

        # 4. 计算大盘资金出逃 vs 个股流动性留存 (Liquidity Retention Ratio)
        # 留存率 = asset_rvol / idx_rvol
        # 在大盘缩量或大出逃时，个股池内资金充沛度
        out_df['liquidity_retention'] = (out_df['asset_rvol'] / out_df['idx_rvol'].replace(0, np.nan)).fillna(1.0)

        # 5. 计算个股与大盘波幅比 (Range Compression)
        asset_tr = out_df['high'] - out_df['low']
        idx_tr = out_df['idx_high'] - out_df['idx_low']
        asset_tr_sma = asset_tr.rolling(window=self.window, min_periods=1).mean()
        idx_tr_sma = idx_tr.rolling(window=self.window, min_periods=1).mean()
        
        out_df['asset_compression'] = asset_tr / asset_tr_sma.replace(0, np.nan).fillna(1e-5)
        out_df['idx_compression'] = idx_tr / idx_tr_sma.replace(0, np.nan).fillna(1e-5)

        # 6. 判定机构级 Hidden Strength (暗藏强势)
        # 公式: Index_Down & Asset_Range_Compress & Liquidity_Retention_High & Downside_Followthrough_Fail
        idx_down = out_df['idx_log_return'] < -0.015
        asset_compress = out_df['asset_compression'] < 0.85
        retention_high = out_df['liquidity_retention'] > 1.2
        fail_down = out_df['asset_log_return'] > -0.005 # 大盘暴跌，个股几乎没跌或上涨
        
        out_df['hidden_strength'] = idx_down & asset_compress & retention_high & fail_down

        # 7. 判定机构级 Hidden Weakness (高位虚拉暗撤)
        # 公式: Index_Up & 放量滞涨 (asset_rvol > 1.5 但 asset_log_return < 0.005) & 相对留存走衰
        idx_up = out_df['idx_log_return'] > 0.015
        stagnation = (out_df['asset_rvol'] > 1.5) & (out_df['asset_log_return'] < 0.005)
        out_df['hidden_weakness'] = idx_up & stagnation

        return out_df

    def extract_summary(self, out_df: pd.DataFrame) -> Dict[str, Any]:
        if out_df.empty:
            return {}
        last = out_df.iloc[-1]

        # 安全地获取字段,如果不存在则使用默认值
        return {
            'liquidity_retention': float(last.get('liquidity_retention', 1.0)),
            'hidden_strength': bool(last.get('hidden_strength', False)),
            'hidden_weakness': bool(last.get('hidden_weakness', False)),
            'idx_log_return': float(last.get('idx_log_return', 0.0)),
            'asset_log_return': float(last.get('asset_log_return', 0.0))
        }
