import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

class BayesianThresholdModel:
    """
    贝叶斯自适应阈值模型
    使用正态-正态共轭先验（Normal-Normal Conjugate Prior）根据个股历史量价特征动态调整判定阈值。
    """
    def __init__(self, prior_breakout_mu=1.5, prior_shrink_mu=0.6, prior_sigma=0.5):
        self.prior_breakout_mu = prior_breakout_mu
        self.prior_shrink_mu = prior_shrink_mu
        self.prior_sigma = prior_sigma
        
        # 精度（方差的倒数）
        self.prior_precision = 1.0 / (prior_sigma ** 2)

        # 初始化后验为先验
        self.breakout_posterior_mu = prior_breakout_mu
        self.shrink_posterior_mu = prior_shrink_mu

    def fit(self, df: pd.DataFrame, breakout_percentile=85, shrink_percentile=15):
        """
        根据历史数据拟合后验阈值
        
        Args:
            df: 包含 'High', 'Low', 'Close', 'Volume' 的 DataFrame
            breakout_percentile: 取振幅最大的前 (100 - breakout_percentile)% 作为突破样本
            shrink_percentile: 取振幅最小的前 shrink_percentile% 作为缩量样本
        """
        try:
            if df is None or len(df) < 20:
                logger.warning("样本数据不足 20 条，贝叶斯模型使用默认先验。")
                return

            # 统一列名为小写或大写（兼容性处理）
            close_col = 'Close' if 'Close' in df.columns else 'close'
            high_col = 'High' if 'High' in df.columns else 'high'
            low_col = 'Low' if 'Low' in df.columns else 'low'
            vol_col = 'Volume' if 'Volume' in df.columns else 'volume'

            # 如果没有计算 Volume_MA20，则临时计算
            vol_ma = df['Volume_MA20'] if 'Volume_MA20' in df.columns else df[vol_col].rolling(20, min_periods=1).mean()

            # 1. 计算振幅 (high - low) / close
            # 为防止除零，取 max(close, 1e-9)
            amplitude = (df[high_col] - df[low_col]) / np.maximum(df[close_col], 1e-9)
            
            # 2. 计算量比 volume / volume_ma20
            volume_ratio = df[vol_col] / np.maximum(vol_ma, 1e-9)

            # 3. 突破样本建模 (高振幅)
            threshold_amp_high = amplitude.quantile(breakout_percentile / 100.0)
            breakout_mask = amplitude >= threshold_amp_high
            breakout_ratios = volume_ratio[breakout_mask].dropna()

            if len(breakout_ratios) >= 10:
                sample_mean = breakout_ratios.mean()
                sample_var = breakout_ratios.var(ddof=1)
                n = len(breakout_ratios)
                
                # 如果方差过小（例如常数数列），设一个极小的底线，避免除以零
                sample_var = max(sample_var, 1e-6)

                # 正态-正态共轭后验均值公式
                posterior_precision = self.prior_precision + n / sample_var
                posterior_mu = (self.prior_breakout_mu * self.prior_precision + n * sample_mean / sample_var) / posterior_precision
                self.breakout_posterior_mu = posterior_mu
            else:
                logger.debug(f"突破样本量不足 ({len(breakout_ratios)} < 10)，沿用先验阈值。")

            # 4. 缩量建模 (低振幅样本)
            threshold_amp_low = amplitude.quantile(shrink_percentile / 100.0)
            shrink_mask = amplitude <= threshold_amp_low
            shrink_ratios = volume_ratio[shrink_mask].dropna()
            
            if len(shrink_ratios) >= 10:
                sample_mean = shrink_ratios.mean()
                sample_var = shrink_ratios.var(ddof=1)
                n = len(shrink_ratios)

                sample_var = max(sample_var, 1e-6)

                posterior_precision = self.prior_precision + n / sample_var
                posterior_mu = (self.prior_shrink_mu * self.prior_precision + n * sample_mean / sample_var) / posterior_precision
                self.shrink_posterior_mu = posterior_mu
            else:
                logger.debug(f"缩量样本量不足 ({len(shrink_ratios)} < 10)，沿用先验阈值。")

        except Exception as e:
            logger.error(f"贝叶斯阈值自适应拟合失败: {e}")
            # 发生异常时静默降级为先验值

    def get_volume_threshold(self, signal_type: str, default: float = 1.5) -> float:
        """
        获取信号专属的后验阈值
        
        Args:
            signal_type: 'breakout' 或 'shrink'
            default: 如果不支持该类型，返回的默认值
        """
        if signal_type == 'breakout':
            return self.breakout_posterior_mu
        elif signal_type == 'shrink':
            return self.shrink_posterior_mu
        else:
            return default
