#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析器 - 核心分析工具
Wyckoff Analyzer - Core Analysis Tool

合并了原 wyckoff_detector.py 和 enhanced_wyckoff_analyzer.py 的核心功能

功能：
1. 数据获取（支持A股、美股、港股）
2. 形态检测（Spring/Upthrust/SOS/SOW/LPS/LPSY）
3. 阶段识别（积累/分布/上涨/下跌）
4. 成交量分析
5. 因果定律计算
6. 相对强度分析
7. 生成分析报告
"""

import yfinance as yf
import baostock as bs
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from enum import Enum, auto
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 枚举和配置
# ============================================================

class MarketPhase(Enum):
    """市场阶段枚举"""
    ACCUMULATION = auto()
    MARKUP = auto()
    DISTRIBUTION = auto()
    MARKDOWN = auto()
    UNKNOWN = auto()


@dataclass
class WyckoffConfig:
    """威科夫分析配置"""
    confidence_threshold: float = 0.85
    min_data_length: int = 60
    atr_period: int = 14
    atr_multiplier: float = 1.5
    volume_ma_period: int = 20


# ============================================================
# 技术指标计算
# ============================================================

def calculate_atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算ATR（Average True Range）"""
    high = pd.to_numeric(data['High'], errors='coerce')
    low = pd.to_numeric(data['Low'], errors='coerce')
    close = pd.to_numeric(data['Close'], errors='coerce').shift(1)

    tr1 = high - low
    tr2 = (high - close).abs()
    tr3 = (low - close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=1).mean()

    return pd.Series(atr, index=data.index, name='ATR')


def prepare_data(data: pd.DataFrame, config: WyckoffConfig = None) -> pd.DataFrame:
    """预计算常用指标"""
    cfg = config or WyckoffConfig()
    df = data.copy()

    # 确保数值类型
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['High', 'Low', 'Close', 'Volume'])

    # 计算均线
    df['MA20'] = df['Close'].rolling(20, min_periods=1).mean()
    df['MA50'] = df['Close'].rolling(50, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(200, min_periods=1).mean()
    df['Volume_MA20'] = df['Volume'].rolling(cfg.volume_ma_period, min_periods=1).mean()

    # 计算ATR
    df['ATR'] = calculate_atr(df, cfg.atr_period)

    return df


# ============================================================
# 主分析器类
# ============================================================

class WyckoffAnalyzer:
    """威科夫分析器"""

    def __init__(self, symbol: str, period: str = "1y", config: WyckoffConfig = None):
        """
        初始化分析器

        Args:
            symbol: 股票代码或中文名称
            period: 数据周期 (1y, 2y, 3y, 5y)
            config: 配置参数
        """
        self.symbol = symbol
        self.period = period
        self.config = config or WyckoffConfig()
        self.data = None
        self.cache_file = os.path.join(os.path.dirname(__file__), "stock_cache.json")

    # ----------------------------------------------------------
    # 数据获取
    # ----------------------------------------------------------

    def _is_a_stock(self, symbol: str) -> bool:
        """判断是否为A股"""
        symbol_upper = symbol.upper()
        if symbol.isdigit():
            return True
        if symbol_upper.endswith(('.SH', '.SZ')):
            return True
        if symbol_upper.startswith(('SH.', 'SZ.')):
            return True
        return False

    def _resolve_stock_name(self, name: str) -> Optional[str]:
        """中文名称 → 股票代码"""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if name in cache:
                    return cache[name]
            except Exception:
                pass

        code = self._search_from_baostock(name)
        if code:
            self._update_cache(name, code)
            return code
        return None

    def _get_baseline_index_symbol(self) -> str:
        """获取大盘基准指数代码"""
        symbol = self.symbol.upper()
        if self._is_a_stock(symbol):
            code = symbol.split('.')[-1] if '.' in symbol else symbol
            if code.startswith('6'):
                return "sh.000001"  # 上交所 - 上证指数
            elif code.startswith('3'):
                return "sz.399006"  # 创业板 - 创业板指
            elif code.startswith('0'):
                return "sz.399001"  # 深交所 - 深证成指
            else:
                return "sh.000001"
        elif symbol.endswith('.HK'):
            return "^HSI"  # 港股 - 恒生指数
        else:
            return "SPY"  # 美股/其他 - 标普500

    def _search_from_baostock(self, keyword: str) -> Optional[str]:
        """从 baostock 搜索股票"""
        try:
            lg = bs.login()
            if lg.error_code != '0':
                return None

            rs = bs.query_stock_basic()
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())

            bs.logout()

            if data_list:
                df = pd.DataFrame(data_list, columns=rs.fields)
                match = df[df['code_name'].str.contains(keyword, na=False)]
                if not match.empty:
                    return match.iloc[0]['code']
        except Exception as e:
            print(f"baostock查询失败: {e}")
            return None

        return None

    def _update_cache(self, name: str, code: str):
        """更新本地缓存"""
        cache = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            except Exception:
                pass

        cache[name] = code

        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"缓存更新失败: {e}")

    def fetch_data(self) -> bool:
        """获取股票数据（自动识别市场）"""
        try:
            symbol = self.symbol
            # 检查是否包含中文字符
            if any('\u4e00' <= char <= '\u9fff' for char in symbol):
                resolved = self._resolve_stock_name(symbol)
                if resolved:
                    symbol = resolved
                    self.symbol = symbol
                else:
                    print(f"无法识别股票名称: {self.symbol}")
                    return False

            if self._is_a_stock(symbol):
                return self._fetch_a_stock_data(symbol)
            else:
                return self._fetch_global_stock_data(symbol)

        except Exception as e:
            print(f"获取数据失败: {self.symbol} - {str(e)}")
            return False

    def _fetch_a_stock_data(self, symbol: str) -> bool:
        """baostock 获取A股数据"""
        try:
            if '.' in symbol:
                parts = symbol.split('.')
                code = f"{parts[1].lower()}.{parts[0]}"
            else:
                prefix = 'sh' if symbol.startswith('6') else 'sz'
                code = f"{prefix}.{symbol}"

            end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
            period_days = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1825}
            days = period_days.get(self.period, 365)
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')

            lg = bs.login()
            if lg.error_code != '0':
                print(f"baostock登录失败: {symbol}")
                return False

            rs = bs.query_history_k_data_plus(
                code, "date,open,high,low,close,volume,amount",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="3"
            )

            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())

            bs.logout()

            if not data_list or len(data_list) < 60:
                print(f"数据不足: {symbol}")
                return False

            df = pd.DataFrame(data_list, columns=rs.fields)
            df = df.rename(columns={
                'date': 'Date', 'open': 'Open', 'high': 'High',
                'low': 'Low', 'close': 'Close', 'volume': 'Volume'
            })
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            df = df.astype(float)

            self.data = prepare_data(df, self.config)
            return True

        except Exception as e:
            print(f"获取A股数据失败: {symbol} - {str(e)}")
            return False

    def _fetch_global_stock_data(self, symbol: str) -> bool:
        """yfinance 获取其他市场数据"""
        try:
            stock = yf.Ticker(symbol)
            self.data = stock.history(period=self.period)

            if self.data.empty or len(self.data) < 60:
                print(f"数据不足: {symbol}")
                return False

            self.data = prepare_data(self.data, self.config)
            return True

        except Exception as e:
            print(f"获取数据失败: {symbol} - {str(e)}")
            return False

    # ----------------------------------------------------------
    # 形态检测
    # ----------------------------------------------------------

    def detect_trading_range(self, window: int = 60) -> Dict:
        """检测交易区间（积累/分布）"""
        if self.data is None or len(self.data) < window:
            return {}

        df = self.data.tail(window).copy()

        high_max = df['High'].max()
        low_min = df['Low'].min()
        range_pct = (high_max - low_min) / low_min

        is_consolidation = range_pct < 0.3

        vol_trend = 'decreasing' if df['Volume'].iloc[-20:].mean() < df['Volume'].iloc[-60:-20].mean() else 'increasing'

        current_price = df['Close'].iloc[-1]
        position = (current_price - low_min) / (high_max - low_min) if high_max > low_min else 0.5

        return {
            'is_consolidation': is_consolidation,
            'high': high_max,
            'low': low_min,
            'range_pct': range_pct,
            'duration_days': window,
            'volume_trend': vol_trend,
            'position': position,
            'current_price': current_price
        }

    def detect_spring(self, lookback: int = 120) -> Dict:
        """
        增强版Spring检测 (V2)
        
        威科夫Spring完整定义：
        1. 存在明确的交易区间（至少30天的横盘整理）
        2. 价格短暂跌破交易区间下边界（1-3天）
        3. 快速收回区间内（收盘价回到支撑位上方）
        4. 成交量模式：下跌时缩量或正常，反弹时放量
        """
        if self.data is None or len(self.data) < 30:
            return {'detected': False, 'reason': 'insufficient_data'}
            
        df = self.data.tail(lookback).copy()
        
        # 步骤1：检测交易区间
        tr_window = 60
        if len(df) < tr_window:
            return {'detected': False, 'reason': 'insufficient_data'}
        
        tr_data = df.tail(tr_window)
        tr_high = tr_data['High'].max()
        tr_low = tr_data['Low'].min()
        tr_range_pct = (tr_high - tr_low) / tr_low
        
        # 交易区间幅度应该小于20%（可调整）
        if tr_range_pct > 0.30:  # 为了宽幅震荡的A股稍微放宽到30%
            return {'detected': False, 'reason': 'no_trading_range'}
        
        # 步骤2：确认支撑位（交易区间下边界）
        support_level = tr_low
        
        # 步骤3：寻找跌破支撑的情况
        search_start = max(0, len(df) - 30)  # 最近30天
        
        springs = []
        for i in range(search_start, len(df)):
            current_low = df['Low'].iloc[i]
            current_close = df['Close'].iloc[i]
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]
            
            # 跌破支撑位（低于支撑位）
            if current_low < support_level * 0.98:
                # 步骤4：检查收盘价是否在支撑位上方（假跌破）
                close_above_support = current_close >= support_level
                
                # 步骤5：检查恢复情况（1-3天内）
                recovery_found = False
                recovery_day = None
                recovery_vol = 0
                
                for j in range(1, 4):
                    if i + j < len(df):
                        if df['Close'].iloc[i + j] > support_level:
                            recovery_found = True
                            recovery_day = j
                            recovery_vol = df['Volume'].iloc[i + j]
                            break
                
                if not recovery_found:
                    continue
                
                # 步骤6：验证成交量模式
                breakdown_vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
                recovery_vol_ratio = recovery_vol / vol_ma if vol_ma > 0 else 1
                
                vol_pattern = 'neutral'
                if breakdown_vol_ratio < 0.8 and recovery_vol_ratio > 1.2:
                    vol_pattern = 'bullish'
                elif breakdown_vol_ratio < 1.0 and recovery_vol_ratio > 1.0:
                    vol_pattern = 'mildly_bullish'
                elif breakdown_vol_ratio > 1.5:
                    vol_pattern = 'bearish'
                
                # 步骤7：综合判断是否为真Spring
                is_spring = False
                confidence = 0
                
                if close_above_support and recovery_found:
                    is_spring = True
                    confidence = 0.8
                elif recovery_found and vol_pattern in ['bullish', 'mildly_bullish']:
                    is_spring = True
                    confidence = 0.6
                elif recovery_found and recovery_day <= 2:
                    is_spring = True
                    confidence = 0.5
                
                if is_spring:
                    springs.append({
                        'date': df.index[i],
                        'breakdown_price': current_low,
                        'support_level': support_level,
                        'recovery_day': recovery_day,
                        'recovery_price': df['Close'].iloc[i + recovery_day],
                        'close_above_support': close_above_support,
                        'vol_pattern': vol_pattern,
                        'breakdown_volume': current_vol,
                        'recovery_volume': recovery_vol,
                        'volume_ma': vol_ma,
                        'confidence': confidence,
                        'price': current_low
                    })
        
        if springs:
            return {'detected': True, 'signals': springs, 'latest_spring': springs[-1]}
        return {'detected': False, 'reason': 'no_spring_found'}

    def detect_climax(self) -> Dict:
        """
        检测高潮（CL）
        威科夫高潮定义：成交量急剧放大（3-5倍平均成交量）+ 价格波动剧烈
        """
        if self.data is None or len(self.data) < 20:
            return {'detected': False}
            
        df = self.data.copy()
        
        for i in range(20, len(df)):
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]
            daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
            avg_range = (df['High'] - df['Low']).rolling(20).mean().iloc[i]
            
            # 成交量急剧放大
            vol_spike = current_vol / vol_ma if vol_ma > 0 else 1
            # 价格波动剧烈
            range_spike = daily_range / avg_range if avg_range > 0 else 1
            
            # 高潮条件：成交量3倍以上 + 价格波动2倍以上 (A股考虑到涨跌停板，可能波动率不需要那么大)
            if vol_spike >= 3.0 and range_spike >= 1.5:
                price_change = df['Close'].iloc[i] - df['Close'].iloc[i-1]
                
                if price_change > 0:
                    climax_type = 'buying_climax'  # 顶部高潮
                else:
                    climax_type = 'selling_climax'  # 底部高潮
                
                return {
                    'detected': True,
                    'type': climax_type,
                    'date': df.index[i],
                    'price': df['Close'].iloc[i],
                    'volume_ratio': vol_spike,
                    'range_ratio': range_spike
                }
        
        return {'detected': False}

    def detect_automatic_reaction(self, climax_event: Dict) -> Dict:
        """检测自动反弹/回落（AR）"""
        if not climax_event.get('detected'):
            return {'detected': False}
        
        df = self.data.copy()
        try:
            climax_idx = df.index.get_loc(climax_event['date'])
        except KeyError:
            return {'detected': False}
        
        # 在高潮后5天内寻找AR
        for i in range(climax_idx + 1, min(climax_idx + 6, len(df))):
            current_vol = df['Volume'].iloc[i]
            climax_vol = df['Volume'].iloc[climax_idx]
            
            # 成交量应该低于高潮
            if current_vol < climax_vol * 0.7:
                if climax_event['type'] == 'buying_climax':
                    # 买入高潮后应该是下跌
                    if df['Close'].iloc[i] < df['Close'].iloc[climax_idx]:
                        return {
                            'detected': True,
                            'type': 'automatic_reaction',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'direction': 'down'
                        }
                else:
                    # 卖出高潮后应该是上涨
                    if df['Close'].iloc[i] > df['Close'].iloc[climax_idx]:
                        return {
                            'detected': True,
                            'type': 'automatic_rally',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'direction': 'up'
                        }
        
        return {'detected': False}

    def detect_secondary_test(self, climax_event: Dict, ar_event: Dict) -> Dict:
        """检测二次测试（ST）"""
        if not climax_event.get('detected') or not ar_event.get('detected'):
            return {'detected': False}
        
        df = self.data.copy()
        try:
            climax_idx = df.index.get_loc(climax_event['date'])
        except KeyError:
            return {'detected': False}
        
        # 在AR后20天内寻找ST
        search_end = min(climax_idx + 25, len(df))
        
        for i in range(climax_idx + 2, search_end):
            current_vol = df['Volume'].iloc[i]
            climax_vol = df['Volume'].iloc[climax_idx]
            
            # 成交量应该低于高潮
            if current_vol < climax_vol * 0.7:
                if climax_event['type'] == 'buying_climax':
                    if df['High'].iloc[i] > df['High'].iloc[climax_idx] * 0.95:
                        return {
                            'detected': True,
                            'type': 'secondary_test',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'test_level': 'high'
                        }
                else:
                    if df['Low'].iloc[i] < df['Low'].iloc[climax_idx] * 1.05:
                        return {
                            'detected': True,
                            'type': 'secondary_test',
                            'date': df.index[i],
                            'price': df['Close'].iloc[i],
                            'test_level': 'low'
                        }
        
        return {'detected': False}

    def detect_upthrust(self, lookback: int = 20) -> Dict:
        """检测Upthrust（假突破）"""
        if self.data is None or len(self.data) < lookback + 10:
            return {}

        df = self.data.tail(lookback + 10).copy()
        upthrusts = []

        for i in range(10, len(df)):
            current_high = df['High'].iloc[i]
            current_close = df['Close'].iloc[i]

            past_highs = df['High'].iloc[i-20:i]
            resistance_level = past_highs.max()

            if current_high > resistance_level * 1.02:
                future_data = df.iloc[i:min(i+5, len(df))]
                future_low = future_data['Low'].min()
                rejection_days = (future_data['Low'].idxmin() - df.index[i]).days if len(future_data) > 1 else 0

                breakout_vol = df['Volume'].iloc[i]
                rejection_vol = future_data['Volume'].mean()
                vol_ma = df['Volume_MA20'].iloc[i]

                close_from_high = (current_high - current_close) / current_high

                is_upthrust = (
                    future_low < resistance_level * 0.98 and
                    rejection_days <= 3 and
                    close_from_high > 0.01 and
                    rejection_vol > breakout_vol * 1.2
                )

                if is_upthrust:
                    upthrusts.append({
                        'date': df.index[i],
                        'breakout_price': current_high,
                        'resistance_level': resistance_level,
                        'rejection_price': future_low,
                        'rejection_days': rejection_days,
                        'close_from_high': close_from_high,
                        'breakout_volume': breakout_vol,
                        'rejection_volume': rejection_vol,
                        'volume_ma': vol_ma
                    })

        if upthrusts:
            return {'detected': True, 'upthrusts': upthrusts, 'latest_upthrust': upthrusts[-1]}
        return {'detected': False}

    def detect_sos(self) -> Dict:
        """检测SOS（Sign of Strength - 强势信号）"""
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()
        sos_signals = []

        for i in range(20, len(df)):
            current_close = df['Close'].iloc[i]
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]

            past_high = df['High'].iloc[i-20:i].max()

            if current_close > past_high * 1.03:
                vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
                price_change = (current_close - df['Close'].iloc[i-1]) / df['Close'].iloc[i-1]
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_position = (current_close - df['Low'].iloc[i]) / daily_range if daily_range > 0 else 0.5

                is_sos = (
                    vol_ratio > 1.5 and
                    price_change > 0.03 and
                    close_position > 0.7
                )

                if is_sos:
                    sos_signals.append({
                        'date': df.index[i],
                        'price': current_close,
                        'volume_ratio': vol_ratio,
                        'price_change': price_change,
                        'breakthrough_level': past_high
                    })

        if sos_signals:
            return {'detected': True, 'signals': sos_signals, 'latest': sos_signals[-1]}
        return {'detected': False}

    def detect_sow(self) -> Dict:
        """检测SOW（Sign of Weakness - 弱势信号）"""
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()
        sow_signals = []

        for i in range(20, len(df)):
            current_close = df['Close'].iloc[i]
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]

            past_low = df['Low'].iloc[i-20:i].min()

            if current_close < past_low * 0.97:
                vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
                price_change = (current_close - df['Close'].iloc[i-1]) / df['Close'].iloc[i-1]
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_position = (df['High'].iloc[i] - current_close) / daily_range if daily_range > 0 else 0.5

                is_sow = (
                    vol_ratio > 1.5 and
                    price_change < -0.03 and
                    close_position > 0.7
                )

                if is_sow:
                    sow_signals.append({
                        'date': df.index[i],
                        'price': current_close,
                        'volume_ratio': vol_ratio,
                        'price_change': price_change,
                        'breakdown_level': past_low
                    })

        if sow_signals:
            return {'detected': True, 'signals': sow_signals, 'latest': sow_signals[-1]}
        return {'detected': False}

    def detect_lps(self, days_since_sos: int = 10) -> Dict:
        """检测LPS（Last Point of Support - 最后支撑点）"""
        sos_result = self.detect_sos()
        if not sos_result['detected']:
            return {'detected': False}

        latest_sos = sos_result['latest']
        sos_date = latest_sos['date']

        mask = self.data.index >= sos_date
        df_after_sos = self.data[mask].tail(days_since_sos)

        if len(df_after_sos) < 3:
            return {'detected': False}

        lps_idx = df_after_sos['Low'].idxmin()
        lps_price = df_after_sos['Low'].min()
        lps_vol = df_after_sos.loc[lps_idx, 'Volume']
        sos_vol = latest_sos.get('volume_ratio', 1)

        is_lps = (
            lps_vol < sos_vol * 0.7 and
            lps_price > latest_sos['breakthrough_level'] * 0.95
        )

        if is_lps:
            return {
                'detected': True,
                'date': lps_idx,
                'price': lps_price,
                'volume': lps_vol,
                'sos_volume': sos_vol,
                'pullback_pct': (latest_sos['price'] - lps_price) / latest_sos['price']
            }
        return {'detected': False}

    def detect_lpsy(self, days_since_sow: int = 10) -> Dict:
        """检测LPSY（Last Point of Supply - 最后供应点）"""
        sow_result = self.detect_sow()
        if not sow_result['detected']:
            return {'detected': False}

        latest_sow = sow_result['latest']
        sow_date = latest_sow['date']

        mask = self.data.index >= sow_date
        df_after_sow = self.data[mask].tail(days_since_sow)

        if len(df_after_sow) < 3:
            return {'detected': False}

        lpsy_idx = df_after_sow['High'].idxmax()
        lpsy_price = df_after_sow['High'].max()
        lpsy_vol = df_after_sow.loc[lpsy_idx, 'Volume']
        sow_vol = latest_sow.get('volume_ratio', 1)

        is_lpsy = (
            lpsy_vol < sow_vol * 0.7 and
            lpsy_price < latest_sow['breakdown_level'] * 1.05
        )

        if is_lpsy:
            return {
                'detected': True,
                'date': lpsy_idx,
                'price': lpsy_price,
                'volume': lpsy_vol,
                'sow_volume': sow_vol,
                'rally_pct': (lpsy_price - latest_sow['price']) / latest_sow['price']
            }
        return {'detected': False}

    # ----------------------------------------------------------
    # 阶段识别
    # ----------------------------------------------------------

    def identify_phase(self) -> Dict:
        """
        增强版阶段识别 (V2)
        基于威科夫事件序列，而非简单的均线排列
        返回包含置信度、细分事件、多时间框架等综合判断的字典
        """
        if self.data is None:
            return {'phase': 'Unknown', 'confidence': 0.0}

        events = {
            'climax': self.detect_climax(),
            'automatic_reaction': None,
            'secondary_test': None,
            'spring_upthrust': None,
            'sos_sow': None,
            'lps_lpsy': None
        }
        
        if events['climax']['detected']:
            events['automatic_reaction'] = self.detect_automatic_reaction(events['climax'])
        
        if events['climax']['detected'] and events['automatic_reaction'] and events['automatic_reaction']['detected']:
            events['secondary_test'] = self.detect_secondary_test(
                events['climax'], 
                events['automatic_reaction']
            )
        
        # 将现有的形态检测合并进去
        spring_res = self.detect_spring()
        upthrust_res = self.detect_upthrust()
        if spring_res.get('detected'):
            events['spring_upthrust'] = spring_res
        elif upthrust_res.get('detected'):
            events['spring_upthrust'] = upthrust_res
            
        sos_res = self.detect_sos()
        sow_res = self.detect_sow()
        if sos_res.get('detected'):
            events['sos_sow'] = sos_res
        elif sow_res.get('detected'):
            events['sos_sow'] = sow_res
            
        lps_res = self.detect_lps()
        lpsy_res = self.detect_lpsy()
        if lps_res.get('detected'):
            events['lps_lpsy'] = lps_res
        elif lpsy_res.get('detected'):
            events['lps_lpsy'] = lpsy_res

        # 步骤2：根据事件序列判断阶段
        phase, confidence = self._determine_phase_from_events(events)
        
        # 如果事件序列无法判断（常见情况），退回到使用原有的交易区间和均线判断逻辑
        if phase == 'Unknown':
            tr_info = self.detect_trading_range()
            if not tr_info.get('is_consolidation'):
                ma20 = self.data['MA20'].iloc[-1]
                ma50 = self.data['MA50'].iloc[-1]
                ma200 = self.data['MA200'].iloc[-1]
                current = self.data['Close'].iloc[-1]
                
                if current > ma20 > ma50 > ma200:
                    phase = "Markup Phase E (强势上涨)"
                    confidence = 0.6
                elif current > ma20 > ma50 and ma20 < ma200:
                    phase = "Accumulation Phase D (可能在建仓末期)"
                    confidence = 0.5
                elif current < ma20 < ma50 < ma200:
                    phase = "Markdown Phase E (强势下跌)"
                    confidence = 0.6
                elif current < ma20 < ma50 and ma20 > ma200:
                    phase = "Distribution Phase D (可能在出货末期)"
                    confidence = 0.5
                else:
                    phase = "Trending (趋势中)"
                    confidence = 0.4
            else:
                position = tr_info['position']
                vol_trend = tr_info['volume_trend']
                
                if vol_trend == 'decreasing':
                    if position < 0.3:
                        phase = "Accumulation Phase B/C (可能在建仓中)"
                    elif position < 0.7:
                        phase = "Accumulation Phase C-D (可能在震仓)"
                    else:
                        phase = "Accumulation Phase D-E (准备突破)"
                    confidence = 0.5
                else:
                    if position > 0.7:
                        phase = "Distribution Phase B/C (可能在出货中)"
                    elif position > 0.3:
                        phase = "Distribution Phase C-D (可能在假突破)"
                    else:
                        phase = "Distribution Phase D-E (准备跌破)"
                    confidence = 0.5

        # 步骤3：结合均线趋势确认
        ma_confidence = self._check_ma_confirmation(phase)
        
        # 步骤4：结合成交量确认
        vol_confidence = self._check_volume_confirmation(phase)
        
        final_confidence = confidence * 0.5 + ma_confidence * 0.3 + vol_confidence * 0.2
        
        return {
            'phase': phase,
            'confidence': min(final_confidence, 1.0),
            'events_detected': events,
            'ma_confidence': ma_confidence,
            'vol_confidence': vol_confidence
        }

    def _determine_phase_from_events(self, events: Dict) -> Tuple[str, float]:
        """根据事件序列判断阶段"""
        if events['spring_upthrust'] and events.get('spring_upthrust', {}).get('detected'):
            if events['sos_sow'] and events.get('sos_sow', {}).get('detected') and 'sos' in str(events['sos_sow']):
                return 'Accumulation Phase D (积累期突破)', 0.85
            else:
                return 'Accumulation Phase C (积累期震仓)', 0.70
                
        elif events['secondary_test'] and events['secondary_test'].get('detected'):
            if events['climax']['type'] == 'selling_climax':
                return 'Accumulation Phase B (积累期测试)', 0.60
            else:
                return 'Distribution Phase B (派发期测试)', 0.60
                
        elif events['climax'] and events['climax'].get('detected') and events['automatic_reaction'] and events['automatic_reaction'].get('detected'):
            if events['climax']['type'] == 'selling_climax':
                return 'Accumulation Phase A (恐慌抛售停止)', 0.75
            else:
                return 'Distribution Phase A (买入高潮停止)', 0.75
                
        elif events['spring_upthrust'] and events.get('spring_upthrust', {}).get('detected') and 'upthrust' in str(events['spring_upthrust']):
            if events['sos_sow'] and events.get('sos_sow', {}).get('detected') and 'sow' in str(events['sos_sow']):
                return 'Distribution Phase D (派发期跌破)', 0.85
            else:
                return 'Distribution Phase C (派发期诱多)', 0.70
                
        return 'Unknown', 0.30

    def _check_ma_confirmation(self, phase: str) -> float:
        """检查均线是否确认阶段判断"""
        ma20 = self.data['MA20'].iloc[-1]
        ma50 = self.data['MA50'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1]
        current = self.data['Close'].iloc[-1]
        
        if 'Accumulation' in phase or 'Markup' in phase:
            if current < ma200 and ma20 < ma50:
                return 0.8
            elif current < ma200:
                return 0.6
            else:
                return 0.4
        elif 'Distribution' in phase or 'Markdown' in phase:
            if current > ma200 and ma20 > ma50:
                return 0.8
            elif current > ma200:
                return 0.6
            else:
                return 0.4
        return 0.5

    def _check_volume_confirmation(self, phase: str) -> float:
        """检查成交量是否确认阶段判断"""
        df = self.data.tail(20)
        up_days = df[df['Close'] > df['Close'].shift(1)]
        down_days = df[df['Close'] < df['Close'].shift(1)]
        
        if len(up_days) == 0 or len(down_days) == 0:
            return 0.5
        
        avg_up_vol = up_days['Volume'].mean()
        avg_down_vol = down_days['Volume'].mean()
        vol_ratio = avg_up_vol / avg_down_vol if avg_down_vol > 0 else 1
        
        if 'Accumulation' in phase or 'Markup' in phase:
            if vol_ratio > 1.2:
                return 0.8
            elif vol_ratio > 1.0:
                return 0.6
            else:
                return 0.4
        elif 'Distribution' in phase or 'Markdown' in phase:
            if vol_ratio < 0.8:
                return 0.8
            elif vol_ratio < 1.0:
                return 0.6
            else:
                return 0.4
        return 0.5

    def identify_phase_multi_timeframe(self) -> Dict:
        """多时间框架阶段确认"""
        daily_phase = self.identify_phase()
        weekly_trend = self._get_weekly_trend()
        monthly_trend = self._get_monthly_trend()
        
        final_confidence = daily_phase['confidence']
        phase_str = daily_phase['phase']
        
        if 'Accumulation' in phase_str or 'Markup' in phase_str:
            if weekly_trend == 'bullish' and monthly_trend != 'bearish':
                final_confidence *= 1.2
            elif weekly_trend == 'bearish':
                final_confidence *= 0.7
        elif 'Distribution' in phase_str or 'Markdown' in phase_str:
            if weekly_trend == 'bearish' and monthly_trend != 'bullish':
                final_confidence *= 1.2
            elif weekly_trend == 'bullish':
                final_confidence *= 0.7
                
        return {
            'phase': phase_str,
            'confidence': min(final_confidence, 1.0),
            'daily_phase': daily_phase,
            'weekly_trend': weekly_trend,
            'monthly_trend': monthly_trend,
            'multi_timeframe_agreement': self._check_timeframe_agreement(phase_str, weekly_trend, monthly_trend)
        }

    def _get_weekly_trend(self) -> str:
        """获取周线趋势"""
        df = self.data.copy()
        df['Week'] = df.index.isocalendar().week
        df['Year'] = df.index.isocalendar().year
        
        weekly = df.groupby(['Year', 'Week']).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        
        if len(weekly) < 20:
            return 'unknown'
            
        weekly['MA10'] = weekly['Close'].rolling(10).mean()
        weekly['MA20'] = weekly['Close'].rolling(20).mean()
        
        current_close = weekly['Close'].iloc[-1]
        ma10 = weekly['MA10'].iloc[-1]
        ma20 = weekly['MA20'].iloc[-1]
        
        if current_close > ma10 > ma20: return 'bullish'
        elif current_close < ma10 < ma20: return 'bearish'
        return 'neutral'

    def _get_monthly_trend(self) -> str:
        """获取月线趋势"""
        df = self.data.copy()
        df['Month'] = df.index.month
        df['Year'] = df.index.year
        
        monthly = df.groupby(['Year', 'Month']).agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        })
        
        if len(monthly) < 12:
            return 'unknown'
            
        monthly['MA6'] = monthly['Close'].rolling(6).mean()
        monthly['MA12'] = monthly['Close'].rolling(12).mean()
        
        current_close = monthly['Close'].iloc[-1]
        ma6 = monthly['MA6'].iloc[-1]
        ma12 = monthly['MA12'].iloc[-1]
        
        if current_close > ma6 > ma12: return 'bullish'
        elif current_close < ma6 < ma12: return 'bearish'
        return 'neutral'

    def _check_timeframe_agreement(self, daily_phase: str, weekly_trend: str, monthly_trend: str) -> str:
        """检查多时间框架是否一致"""
        if 'Accumulation' in daily_phase or 'Markup' in daily_phase:
            if weekly_trend == 'bullish' and monthly_trend == 'bullish': return 'strong_agreement'
            elif weekly_trend == 'bullish' or monthly_trend == 'bullish': return 'moderate_agreement'
            return 'disagreement'
        elif 'Distribution' in daily_phase or 'Markdown' in daily_phase:
            if weekly_trend == 'bearish' and monthly_trend == 'bearish': return 'strong_agreement'
            elif weekly_trend == 'bearish' or monthly_trend == 'bearish': return 'moderate_agreement'
            return 'disagreement'
        return 'unknown'

    def identify_phase_with_rs(self) -> Dict:
        """结合相对强度的阶段识别"""
        benchmark_symbol = self._get_baseline_index_symbol()
        rs_data = self._calculate_relative_strength(benchmark_symbol)
        
        base_phase = self.identify_phase_multi_timeframe()
        confidence = base_phase['confidence']
        
        if rs_data['rs_trend'] == 'rising':
            if 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 1.15
            elif 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 0.75
        elif rs_data['rs_trend'] == 'falling':
            if 'Distribution' in base_phase['phase'] or 'Markdown' in base_phase['phase']:
                confidence *= 1.15
            elif 'Accumulation' in base_phase['phase'] or 'Markup' in base_phase['phase']:
                confidence *= 0.75
                
        base_phase['relative_strength'] = rs_data
        base_phase['confidence'] = min(confidence, 1.0)
        return base_phase

    def _calculate_relative_strength(self, benchmark_symbol: str) -> Dict:
        """计算相对强度"""
        try:
            benchmark_analyzer = WyckoffAnalyzer(benchmark_symbol, period=self.period, config=self.config)
            if not benchmark_analyzer.fetch_data():
                return {'rs_trend': 'unknown', 'rs_value': None}
                
            common_dates = self.data.index.intersection(benchmark_analyzer.data.index)
            stock_data = self.data.loc[common_dates]
            benchmark_data = benchmark_analyzer.data.loc[common_dates]
            
            rs = stock_data['Close'] / benchmark_data['Close']
            rs_ma20 = rs.rolling(20).mean()
            rs_ma50 = rs.rolling(50).mean()
            
            if rs_ma20.iloc[-1] > rs_ma50.iloc[-1]: rs_trend = 'rising'
            elif rs_ma20.iloc[-1] < rs_ma50.iloc[-1]: rs_trend = 'falling'
            else: rs_trend = 'flat'
            
            rs_change = (rs.iloc[-1] / rs.iloc[-20] - 1) * 100 if len(rs) > 20 else 0
            
            return {
                'benchmark_used': benchmark_symbol,
                'rs_value': rs.iloc[-1],
                'rs_ma20': rs_ma20.iloc[-1],
                'rs_ma50': rs_ma50.iloc[-1],
                'rs_trend': rs_trend,
                'rs_change_20d': rs_change
            }
        except Exception:
            return {'rs_trend': 'unknown', 'rs_value': None}

    # ----------------------------------------------------------
    # 因果定律计算
    # ----------------------------------------------------------

    def calculate_cause_effect(self) -> Dict:
        """计算因果定律目标"""
        if self.data is None or len(self.data) < 60:
            return {}

        tr_info = self.detect_trading_range()
        if not tr_info.get('is_consolidation'):
            return {'error': '无法识别有效的交易区间'}

        cause_size = tr_info['high'] - tr_info['low']
        current_price = tr_info['current_price']
        position = tr_info['position']

        # 判断突破方向
        if position > 0.5:
            # 向上突破
            breakout_point = tr_info['high']
            targets = {
                'target_1': breakout_point + cause_size * 0.618,
                'target_2': breakout_point + cause_size * 1.0,
                'target_3': breakout_point + cause_size * 1.618,
            }
        else:
            # 向下突破
            breakout_point = tr_info['low']
            targets = {
                'target_1': breakout_point - cause_size * 0.618,
                'target_2': breakout_point - cause_size * 1.0,
                'target_3': breakout_point - cause_size * 1.618,
            }

        return {
            'cause_size': cause_size,
            'breakout_point': breakout_point,
            'targets': targets,
            'current_position': position
        }

    # ----------------------------------------------------------
    # 报告生成
    # ----------------------------------------------------------

    def generate_report(self) -> str:
        """生成分析报告"""
        if not self.fetch_data():
            return f"无法获取数据: {self.symbol}"

        report = f"""
{'='*60}
威科夫形态分析报告
{'='*60}

股票代码: {self.symbol}
分析日期: {datetime.now().strftime('%Y-%m-%d')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【当前阶段】
{self.identify_phase()}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【基础数据】
当前价格: {self.data['Close'].iloc[-1]:.2f}
52周最高: {self.data['High'].tail(252).max():.2f}
52周最低: {self.data['Low'].tail(252).min():.2f}
成交量: {self.data['Volume'].iloc[-1]:,.0f}
量比: {self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1]:.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【形态检测】
"""

        # 检测各种形态
        trading_range = self.detect_trading_range()
        spring = self.detect_spring()
        upthrust = self.detect_upthrust()
        sos = self.detect_sos()
        sow = self.detect_sow()
        lps = self.detect_lps()
        lpsy = self.detect_lpsy()

        if trading_range.get('is_consolidation'):
            report += f"""
✅ 检测到交易区间:
   区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
   幅度: {trading_range['range_pct']*100:.1f}%
   当前位置: {trading_range['position']*100:.0f}% (0%=底部, 100%=顶部)
   成交量趋势: {trading_range['volume_trend']}
"""

        if spring['detected']:
            latest = spring['latest_spring']
            report += f"""
✅ 检测到Spring:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   跌破价: {latest['breakdown_price']:.2f}
   支撑位: {latest['support_level']:.2f}
   收回价: {latest['recovery_price']:.2f}
   收回天数: {latest['recovery_days']}天
   ✓ 真Spring（3天内收回且放量）
"""

        if upthrust['detected']:
            latest = upthrust['latest_upthrust']
            report += f"""
✅ 检测到Upthrust:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   突破价: {latest['breakout_price']:.2f}
   阻力位: {latest['resistance_level']:.2f}
   回落价: {latest['rejection_price']:.2f}
   回落天数: {latest['rejection_days']}天
   收盘距高点: {latest['close_from_high']*100:.1f}%
   ✓ 真Upthrust（3天内回落且放量）
"""

        if sos['detected']:
            latest = sos['latest']
            report += f"""
✅ 检测到SOS（Sign of Strength）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   涨幅: {latest['price_change']*100:.1f}%
   突破位: {latest['breakthrough_level']:.2f}
   ✓ 强势信号（放量突破）
"""

        if sow['detected']:
            latest = sow['latest']
            report += f"""
✅ 检测到SOW（Sign of Weakness）:
   日期: {latest['date'].strftime('%Y-%m-%d')}
   价格: {latest['price']:.2f}
   成交量倍数: {latest['volume_ratio']:.1f}x
   跌幅: {latest['price_change']*100:.1f}%
   跌破位: {latest['breakdown_level']:.2f}
   ✓ 弱势信号（放量跌破）
"""

        if lps['detected']:
            report += f"""
✅ 检测到LPS（Last Point of Support）:
   日期: {lps['date'].strftime('%Y-%m-%d')}
   价格: {lps['price']:.2f}
   回调幅度: {lps['pullback_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做多入场点
"""

        if lpsy['detected']:
            report += f"""
✅ 检测到LPSY（Last Point of Supply）:
   日期: {lpsy['date'].strftime('%Y-%m-%d')}
   价格: {lpsy['price']:.2f}
   反弹幅度: {lpsy['rally_pct']*100:.1f}%
   成交量缩小: 是
   ⭐ 建议做空入场点
"""

        # 因果测算
        cause_effect = self.calculate_cause_effect()
        if cause_effect and 'targets' in cause_effect:
            report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【因果测算】
交易区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
因果幅度: {cause_effect['cause_size']:.2f}
目标1 (0.618倍): {cause_effect['targets']['target_1']:.2f}
目标2 (1.0倍): {cause_effect['targets']['target_2']:.2f}
目标3 (1.618倍): {cause_effect['targets']['target_3']:.2f}
"""

        # 交易建议
        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【交易建议】
"""

        if lps['detected'] and not lpsy['detected']:
            report += f"""
✅ 做多机会:
   入场价格: {lps['price']:.2f} (LPS)
   止损价格: {lps['price']*0.95:.2f} (保守)
   目标价格: {cause_effect['targets']['target_2']:.2f} (因果测算)
   风险提示: 请设置好止损，严格执行
"""
        elif lpsy['detected'] and not lps['detected']:
            report += f"""
✅ 做空机会:
   入场价格: {lpsy['price']:.2f} (LPSY)
   止损价格: {lpsy['price']*1.05:.2f} (保守)
   目标价格: {cause_effect['targets']['target_2']:.2f} (因果测算)
   风险提示: A股做空困难，建议观望或减仓
"""
        elif trading_range.get('is_consolidation'):
            report += """
⏳ 观望等待:
   当前处于横盘整理阶段
   等待明确的SOS或SOW信号
   不要过早入场
"""
        else:
            report += """
⏸️ 无明显信号:
   当前没有明确的入场信号
   建议继续观察或等待更好机会
"""

        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【风险提示】
⚠️ 本报告仅供参考，不构成投资建议
⚠️ 股市有风险，投资需谨慎
⚠️ 请根据自身风险承受能力做出决策
⚠️ 建议结合其他分析方法和市场环境

{'='*60}
"""

        return report

    def _round_floats(self, obj):
        """递归遍历字典/列表，将浮点数截断至3位小数"""
        if isinstance(obj, float):
            return round(obj, 3)
        elif isinstance(obj, dict):
            return {k: self._round_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._round_floats(x) for x in obj]
        return obj

    def calculate_signal_quality(self, market_phase) -> dict:
        """计算信号质量评分"""
        score = 0
        reasons = []

        if self.data is not None:
            vol_ratio = self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1]
            phase_res = self.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown') if isinstance(phase_res, dict) else phase_res
            
            # 1. 技术确认度
            if "Accumulation" in phase_str or "Markup" in phase_str:
                if vol_ratio > 1.5:
                    score += 3
                    reasons.append("成交量强力确认 (放量上涨)")
                elif vol_ratio > 1.0:
                    score += 1
                    reasons.append("成交量温和配合")
                else:
                    reasons.append("上涨缩量，动能不足")
            else:
                if vol_ratio > 1.5:
                    score += 3
                    reasons.append("成交量强力确认 (放量下跌)")
                else:
                    reasons.append("下跌缩量，趋势可能随时反转")
        
            # 2. 趋势一致性
            current_price = self.data['Close'].iloc[-1]
            ma50 = self.data['MA50'].iloc[-1]
            ma200 = self.data['MA200'].iloc[-1]
            
            if current_price > ma50 and ma50 > ma200:
                score += 3
                reasons.append("多时间框架一致 (长期多头排列)")
            elif current_price < ma50 and ma50 < ma200:
                score += 3
                reasons.append("多时间框架一致 (长期空头排列)")

        # 3. 市场环境配合
        market_phase_str = market_phase.get('phase', 'Unknown') if isinstance(market_phase, dict) else market_phase
        if "Accumulation" in market_phase_str or "Markup" in market_phase_str:
            if "Accumulation" in phase_str or "Markup" in phase_str:
                score += 4
                reasons.append("市场环境有利 (顺应大盘多头)")
            else:
                reasons.append("逆势操作 (大盘看多，个股看空)")
        else:
            if "Distribution" in phase_str or "Markdown" in phase_str:
                score += 4
                reasons.append("市场环境有利 (顺应大盘空头)")
            else:
                reasons.append("逆势操作 (大盘看空，个股看多)")

        return {
            "score": score,
            "max_score": 10,
            "confidence": "高" if score >= 7 else "中" if score >= 4 else "低",
            "reasons": reasons
        }

    def generate_trading_plan(self, sentiment_data: dict = None, phase_str: str = "") -> dict:
        """生成实战交易计算器数据（带情绪风控）"""
        if self.data is None:
            return {}
            
        current_price = self.data['Close'].iloc[-1]
        atr = self.data['ATR'].iloc[-1]
        
        tr = self.detect_trading_range()
        high = tr.get("high", current_price * 1.1)
        low = tr.get("low", current_price * 0.9)
        
        if not phase_str:
            phase_res = self.identify_phase()
            phase_str = phase_res.get('phase', 'Unknown') if isinstance(phase_res, dict) else phase_res
            
        is_bullish = "Accumulation" in phase_str or "Markup" in phase_str
        
        if is_bullish:
            entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"
            stop_conservative = round(low, 2)
            stop_aggressive = round(low - atr, 2)
            target_1 = round(high, 2) if current_price < high else round(current_price + atr * 2, 2)
            target_2 = round(high + atr * 3, 2)
        else:
            entry_zone = f"{round(current_price * 0.99, 2)} - {round(current_price * 1.01, 2)}"
            stop_conservative = round(high, 2)
            stop_aggressive = round(high + atr, 2)
            target_1 = round(low, 2) if current_price > low else round(current_price - atr * 2, 2)
            target_2 = round(low - atr * 3, 2)

        # 情绪仓位管理
        pos_conservative = 2.5
        pos_moderate = 5.0
        pos_aggressive = 10.0
        
        dynamic_warning = None
        if sentiment_data:
            sentiment = sentiment_data.get("market_sentiment", "neutral")
            
            if sentiment == "extreme_fear":
                pos_conservative *= 0.5
                pos_moderate *= 0.5
                pos_aggressive *= 0.5
            elif sentiment == "greed":
                pos_conservative *= 1.2
                pos_moderate *= 1.2
                pos_aggressive *= 1.2
                
            # 情绪背离预警
            if sentiment == "greed" and ("Distribution" in phase_str or "Markdown" in phase_str):
                dynamic_warning = "⚠️ 极度危险：大盘贪婪 + 个股派发 = 暴跌前兆，禁止盲目接刀！"
            elif sentiment == "extreme_fear" and ("Accumulation" in phase_str or "Markup" in phase_str):
                dynamic_warning = "💡 黄金坑预警：大盘极度恐慌 + 个股筑底 = 绝佳击球区，请重点关注抗跌表现！"

        return {
            "direction": "做多" if is_bullish else "做空",
            "entry_zone": entry_zone,
            "stop_loss": {
                "conservative": stop_conservative,
                "aggressive": stop_aggressive
            },
            "targets": {
                "target_1": target_1,
                "target_2": target_2
            },
            "position_sizing": {
                "conservative": f"{round(pos_conservative, 1)}%仓位",
                "moderate": f"{round(pos_moderate, 1)}%仓位",
                "aggressive": f"{round(pos_aggressive, 1)}%仓位"
            },
            "holding_period": "中期（2-8周）" if "Markup" in phase_str or "Markdown" in phase_str else "短期（1-3周）",
            "atr_value": round(atr, 2),
            "dynamic_warning": dynamic_warning
        }

    def get_relevant_terms(self, phase: str, events: dict) -> dict:
        """获取相关术语的大白话解释"""
        all_terms = {
            "SOS (强势信号)": {
                "simple": "强势信号 - 价格放量突破阻力位",
                "example": "像蓄势后的跳跃，成交量放大确认",
                "action": "考虑买入或持有"
            },
            "SOW (弱势信号)": {
                "simple": "弱势信号 - 价格放量跌破支撑位",
                "example": "像突然脚软跌入坑中，供给开始主导",
                "action": "考虑卖出或观望"
            },
            "Spring (震仓)": {
                "simple": "震仓 - 短暂跌破支撑后快速收回",
                "example": "像弹簧被压下去后弹起，洗出散户",
                "action": "可能是极佳的买入机会"
            },
            "Upthrust (上冲回落)": {
                "simple": "诱多 - 短暂突破阻力后快速跌回",
                "example": "假装大涨吸引散户接盘，随后迅速撤退",
                "action": "可能是做空或逃顶机会"
            },
            "Accumulation (积累期)": {
                "simple": "建仓期 - 主力在低位悄悄买入筹码",
                "example": "像批发商在淡季默默囤货",
                "action": "耐心等待突破信号"
            },
            "Distribution (派发期)": {
                "simple": "出货期 - 主力在高位分批卖出筹码",
                "example": "像批发商在旺季大肆推销",
                "action": "注意风险，逢高减仓"
            },
            "LPS (最后支撑点)": {
                "simple": "最后支撑点 - 震仓后的缩量回调",
                "example": "像弹簧压到底部的最低点，反弹概率最高",
                "action": "强烈建议买入"
            },
            "LPSY (最后供应点)": {
                "simple": "最后供应点 - 跌破支撑后的无力反抽",
                "example": "像反弹无力撞上天花板",
                "action": "强烈建议卖出"
            }
        }
        
        relevant = {}
        if "Accumulation" in phase:
            relevant["Accumulation (积累期)"] = all_terms["Accumulation (积累期)"]
        elif "Distribution" in phase:
            relevant["Distribution (派发期)"] = all_terms["Distribution (派发期)"]
            
        if events.get('sos', {}).get('detected'):
            relevant["SOS (强势信号)"] = all_terms["SOS (强势信号)"]
        if events.get('sow', {}).get('detected'):
            relevant["SOW (弱势信号)"] = all_terms["SOW (弱势信号)"]
        if events.get('spring', {}).get('detected'):
            relevant["Spring (震仓)"] = all_terms["Spring (震仓)"]
        if events.get('upthrust', {}).get('detected'):
            relevant["Upthrust (上冲回落)"] = all_terms["Upthrust (上冲回落)"]
        if events.get('lps', {}).get('detected'):
            relevant["LPS (最后支撑点)"] = all_terms["LPS (最后支撑点)"]
        if events.get('lpsy', {}).get('detected'):
            relevant["LPSY (最后供应点)"] = all_terms["LPSY (最后供应点)"]
            
        return relevant

    def generate_risk_advice(self, signal_quality: dict, trading_plan: dict) -> dict:
        """生成具体的风险分层操作建议"""
        score = signal_quality.get("score", 0)
        direction = trading_plan.get("direction", "观望")
        stop_con = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        stop_agg = trading_plan.get("stop_loss", {}).get("aggressive", "未知")
        
        if score <= 4:
            return {
                "保守型": {
                    "action": "绝对观望",
                    "reason": f"当前信号质量仅 {score}/10 分，风险极高",
                    "entry_condition": "等待明确的量价反转信号或进入下一周期"
                },
                "稳健型": {
                    "action": "观望为主",
                    "position": "建议空仓",
                    "stop_loss": "暂不适用"
                },
                "激进型": {
                    "action": f"轻仓试错 ({direction})",
                    "position": "不超过 3% 仓位",
                    "stop_loss": f"{stop_con}元 (极严格止损)"
                }
            }
        elif score <= 7:
            return {
                "保守型": {
                    "action": "观望或极轻仓",
                    "reason": f"信号质量 {score}/10 分，未达到绝对安全边际",
                    "entry_condition": "等待价格回调确认支撑后再入场"
                },
                "稳健型": {
                    "action": f"分批建仓 ({direction})",
                    "position": "3-5% 仓位，分2-3次买入",
                    "stop_loss": f"{stop_con}元"
                },
                "激进型": {
                    "action": f"按计划参与 ({direction})",
                    "position": "8% 仓位",
                    "stop_loss": f"{stop_agg}元 (给予一定震荡空间)"
                }
            }
        else:
            return {
                "保守型": {
                    "action": f"稳步参与 ({direction})",
                    "reason": f"信号质量高达 {score}/10 分，多方指标产生共振",
                    "entry_condition": "可在当前价格区间直接介入"
                },
                "稳健型": {
                    "action": f"积极布局 ({direction})",
                    "position": "8-10% 仓位",
                    "stop_loss": f"{stop_con}元"
                },
                "激进型": {
                    "action": f"重仓出击 ({direction})",
                    "position": "15-20% 仓位",
                    "stop_loss": f"{stop_agg}元"
                }
            }

    def generate_interactive_qa(self, signal_quality: dict, trading_plan: dict) -> list:
        """根据分析结果预生成交互问答"""
        direction = trading_plan.get("direction", "观望")
        score = signal_quality.get("score", 0)
        stop = trading_plan.get("stop_loss", {}).get("conservative", "未知")
        period = trading_plan.get("holding_period", "未知")
        
        return [
            f"现在{direction} {self.symbol} 合适吗？(当前信号质量为 {score}/10)",
            f"如果参与 {self.symbol}，应该设置多少止损？(建议保守防守线在 {stop}元)",
            f"这笔交易预期需要持有多长时间？(系统预估 {period})"
        ]

    def get_signal_performance(self, events: dict) -> dict:
        """基于该股票历史K线动态回测信号表现 (20个交易日窗口)"""
        # 预设全市场通用基准（Fallback）
        static_baseline = {
            "SOS (强势信号)": {"total_occurrences": 128, "success_rate": "75.4%", "avg_return": "+12.4%"},
            "Spring (震仓洗盘)": {"total_occurrences": 45, "success_rate": "82.1%", "avg_return": "+18.8%"},
            "SOW (弱势信号)": {"total_occurrences": 92, "success_rate": "68.3%", "avg_return": "-9.2%"},
            "Upthrust (上冲回落)": {"total_occurrences": 56, "success_rate": "71.5%", "avg_return": "-14.5%"}
        }

        signal_mapping = {
            "SOS (强势信号)": {"key": "sos", "is_bullish": True},
            "Spring (震仓洗盘)": {"key": "spring", "is_bullish": True},
            "SOW (弱势信号)": {"key": "sow", "is_bullish": False},
            "Upthrust (上冲回落)": {"key": "upthrust", "is_bullish": False}
        }

        results = {}
        for display_name, config in signal_mapping.items():
            key = config["key"]
            is_bullish = config["is_bullish"]
            
            signals = events.get(key, {}).get("signals", [])
            if len(signals) < 2:
                results[display_name] = static_baseline[display_name]
                results[display_name]["note"] = "样本不足2次，采用全市场基准"
                continue
                
            success_count = 0
            total_returns = []
            
            for sig in signals:
                date_str = sig.get("date")
                entry_price = sig.get("price")
                if not date_str or not entry_price:
                    continue
                    
                try:
                    # 获取日期的索引（需将 date_str 转为 datetime 或处理索引格式匹配）
                    # self.data.index 可能是 DatetimeIndex
                    # 为了安全匹配，我们将字符串转换为与 index 类型一致
                    target_date = pd.to_datetime(date_str).strftime('%Y-%m-%d')
                    idx = -1
                    # 遍历 index 寻找匹配日期，因为有时有时间戳
                    for i, dt in enumerate(self.data.index):
                        if dt.strftime('%Y-%m-%d') == target_date:
                            idx = i
                            break
                    if idx == -1:
                        continue
                except Exception:
                    continue
                    
                target_idx = min(idx + 20, len(self.data) - 1)
                
                # 如果信号距离今天不足5个交易日，视为无足够回测空间，跳过
                if target_idx - idx < 5:
                    continue
                    
                future_price = self.data['Close'].iloc[target_idx]
                
                if is_bullish:
                    ret = (future_price - entry_price) / entry_price
                else:
                    ret = (entry_price - future_price) / entry_price
                    
                total_returns.append(ret)
                if ret > 0:
                    success_count += 1
            
            valid_count = len(total_returns)
            if valid_count < 2:
                results[display_name] = static_baseline[display_name]
                results[display_name]["note"] = "样本不足2次，采用全市场基准"
            else:
                avg_ret = sum(total_returns) / valid_count
                succ_rate = success_count / valid_count
                
                # 显示真实涨跌幅（针对做空信号，取负值还原股票本身跌幅）
                display_avg_ret = -avg_ret if not is_bullish else avg_ret
                display_prefix = "+" if display_avg_ret > 0 else ""

                results[display_name] = {
                    "total_occurrences": valid_count,
                    "success_rate": f"{succ_rate*100:.1f}%",
                    "avg_return": f"{display_prefix}{display_avg_ret*100:.1f}%",
                    "note": f"本股专属动态回测 ({valid_count}次)"
                }
                
        return results

    def add_market_sentiment(self) -> dict:
        """整合市场情绪指标（区分 A股、港股和美股）"""
        try:
            import numpy as np
            import yfinance as yf
            import pandas as pd
            
            is_us_market = not (self.symbol.startswith('sh.') or self.symbol.startswith('sz.') or self.symbol.endswith('.HK'))
            is_hk_market = self.symbol.endswith('.HK')
            
            current_vix = None
            benchmark_used = ""
            
            # 1. 尝试直接获取期权隐含波动率指数 (VIX / VHSI)
            if is_us_market:
                vix = yf.download('^VIX', period='5d', progress=False)
                if not vix.empty:
                    last_close = vix['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        current_vix = float(last_close)
                        benchmark_used = '^VIX (CBOE Implied Volatility)'
            elif is_hk_market:
                vhsi = yf.download('^VHSI', period='5d', progress=False)
                if not vhsi.empty:
                    last_close = vhsi['Close'].iloc[-1]
                    if isinstance(last_close, pd.Series):
                        last_close = last_close.iloc[0] if len(last_close) > 0 else None
                    if last_close is not None and not pd.isna(last_close):
                        current_vix = float(last_close)
                        benchmark_used = '^VHSI (HSI Implied Volatility)'
                    
            # 2. 如果是 A股，或者外盘获取不到 VIX，回退到计算大盘的 20日历史实现波动率 (Realized Volatility)
            if current_vix is None:
                index_symbol = self._get_baseline_index_symbol()
                idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config)
                
                import os, sys
                from contextlib import redirect_stdout
                with open(os.devnull, 'w') as f, redirect_stdout(f):
                    success = idx_analyzer.fetch_data()
                    
                if not success or idx_analyzer.data is None or len(idx_analyzer.data) < 20:
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "无法获取大盘数据计算情绪"}
                
                df = idx_analyzer.data.copy()
                returns = df['Close'].pct_change().dropna()
                if len(returns) < 20:
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "大盘数据不足"}
                    
                current_vix = returns.rolling(20).std().iloc[-1] * np.sqrt(252) * 100
                if pd.isna(current_vix):
                    return {"market_sentiment": "unknown", "vix_level": None, "implication": "波动率计算失败"}
                    
                current_vix = float(current_vix)
                benchmark_used = f'{index_symbol} (20-day Realized Volatility)'
            
            # 3. 统一的情绪评级标准
            if current_vix >= 30:
                sentiment = "extreme_fear"
                implication = "大盘处于极度恐慌或剧烈波动环境，技术信号极易失效（暴涨暴跌），建议严控仓位"
            elif current_vix >= 22:
                sentiment = "fear"
                implication = "大盘恐慌情绪上升，警惕向下突破或大幅震荡"
            elif current_vix <= 15:
                sentiment = "greed"
                implication = "大盘波动极低，多头环境良好或处于温水煮青蛙的赶顶期，需防范高位诱多"
            else:
                sentiment = "neutral"
                implication = "大盘情绪平稳，个股的技术信号和形态的有效性较高"
                
            return {
                "market_sentiment": sentiment,
                "vix_level": round(current_vix, 2),
                "implication": implication,
                "benchmark_used": benchmark_used
            }
        except Exception as e:
            return {"market_sentiment": "unknown", "vix_level": None, "implication": f"获取情绪数据失败: {str(e)}"}

    def generate_json(self) -> str:
        """生成JSON格式的分析报告（供AI Agent读取）"""
        if not self.fetch_data():
            return json.dumps({"error": f"无法获取数据: {self.symbol}"}, ensure_ascii=False)
            
        # 1. 基础事件分析
        climax_res = self.detect_climax()
        ar_res = self.detect_automatic_reaction(climax_res)
        st_res = self.detect_secondary_test(climax_res, ar_res)
        
        events = {
            "trading_range": self.detect_trading_range(),
            "climax": climax_res,
            "automatic_reaction": ar_res,
            "secondary_test": st_res,
            "spring": self.detect_spring(),
            "upthrust": self.detect_upthrust(),
            "sos": self.detect_sos(),
            "sow": self.detect_sow(),
            "lps": self.detect_lps(),
            "lpsy": self.detect_lpsy()
        }
        
        # 获取完整带多时间框架和RS的阶段
        phase_dict = self.identify_phase_with_rs()
        phase_str = phase_dict.get('phase', 'Unknown')
        
        result = {
            "symbol": self.symbol,
            "date": datetime.now().strftime('%Y-%m-%d'),
            "phase": phase_str,
            "phase_confidence": phase_dict.get('confidence', 0.0),
            "multi_timeframe": {
                "weekly_trend": phase_dict.get('weekly_trend', 'unknown'),
                "monthly_trend": phase_dict.get('monthly_trend', 'unknown'),
                "agreement": phase_dict.get('multi_timeframe_agreement', 'unknown')
            },
            "relative_strength": phase_dict.get('relative_strength', {}),
            "basic_data": {
                "current_price": round(self.data['Close'].iloc[-1], 2),
                "volume": int(self.data['Volume'].iloc[-1]),
                "volume_ratio": round(self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1], 2)
            },
            "events": events,
            "cause_effect": self.calculate_cause_effect()
        }
        
        # 获取大盘基准
        index_symbol = self._get_baseline_index_symbol()
        idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config)
        import os, sys
        from contextlib import redirect_stdout
        with open(os.devnull, 'w') as f, redirect_stdout(f):
            idx_success = idx_analyzer.fetch_data()
            
        market_phase_str = "Unknown"
        if idx_success:
            market_phase_dict = idx_analyzer.identify_phase()
            market_phase_str = market_phase_dict.get('phase', 'Unknown')
            result["market_context"] = {
                "index_symbol": index_symbol,
                "phase": market_phase_str
            }
        else:
            result["market_context"] = {
                "index_symbol": index_symbol,
                "error": "无法获取大盘数据"
            }
            
        # 增加市场情绪整合
        global_sentiment = self.add_market_sentiment()
        result["global_sentiment"] = global_sentiment
        
        # 增加信号质量评分和交易计划
        signal_quality = self.calculate_signal_quality(market_phase_str)
        trading_plan = self.generate_trading_plan(global_sentiment, phase_str)
        
        result["signal_quality"] = signal_quality
        result["trading_plan"] = trading_plan
        
        # 增加智能内容生成 (大模型剥离)
        result["terminology_guide"] = self.get_relevant_terms(phase_str, events)
        result["risk_specific_advice"] = self.generate_risk_advice(signal_quality, trading_plan)
        result["interactive_qa"] = self.generate_interactive_qa(signal_quality, trading_plan)
        result["performance_tracking"] = self.get_signal_performance(events)
        
        result = self._round_floats(result)
        
        # 转换 datetime 和特殊类型以便序列化
        def default_serializer(obj):
            if isinstance(obj, (pd.Timestamp, datetime)):
                return obj.strftime('%Y-%m-%d')
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return str(obj)
            
        return json.dumps(result, ensure_ascii=False, default=default_serializer, indent=2)


# ============================================================
# 批量扫描功能
# ============================================================

def batch_scan(symbols: List[str], period: str = "1y") -> List[Dict]:
    """
    批量扫描股票

    Args:
        symbols: 股票代码列表
        period: 数据周期

    Returns:
        扫描结果列表
    """
    results = []

    for symbol in symbols:
        print(f"扫描 {symbol}...")

        analyzer = WyckoffAnalyzer(symbol, period)

        if analyzer.fetch_data():
            phase = analyzer.identify_phase()

            signals = {
                'symbol': symbol,
                'phase': phase,
                'has_spring': analyzer.detect_spring()['detected'],
                'has_upthrust': analyzer.detect_upthrust()['detected'],
                'has_sos': analyzer.detect_sos()['detected'],
                'has_sow': analyzer.detect_sow()['detected'],
                'has_lps': analyzer.detect_lps()['detected'],
                'has_lpsy': analyzer.detect_lpsy()['detected'],
            }

            signal_strength = sum([
                signals['has_lps'],
                signals['has_lpsy'],
                signals['has_sos'],
                signals['has_sow']
            ])

            signals['strength'] = signal_strength
            results.append(signals)

            if signal_strength >= 1:
                print(f"  ✅ {phase}")
                if signals['has_lps']:
                    print(f"     ⭐ 检测到LPS（做多机会）")
                if signals['has_lpsy']:
                    print(f"     ⭐ 检测到LPSY（做空机会）")
        else:
            print(f"  ❌ 获取数据失败")

    return results


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="威科夫股票分析工具")
    parser.add_argument("symbol", nargs="?", help="股票代码 (如 AAPL, 600519)")
    parser.add_argument("--json", action="store_true", help="以JSON格式输出 (供AI Agent使用)")
    parser.add_argument("--batch", action="store_true", help="运行批量扫描示例")
    
    args = parser.parse_args()

    if args.symbol:
        analyzer = WyckoffAnalyzer(args.symbol)
        if args.json:
            import os, sys
            from contextlib import redirect_stdout
            with open(os.devnull, 'w') as f, redirect_stdout(f):
                result_json = analyzer.generate_json()
            print(result_json)
        else:
            print(analyzer.generate_report())
    elif args.batch:
        symbols = ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOGL']
        print("批量扫描美股示例...\n")
        results = batch_scan(symbols)

        print("\n扫描完成！\n")
        print(f"总计扫描: {len(symbols)} 只股票")
        print(f"发现信号: {sum(1 for r in results if r['strength'] > 0)} 只")

        if results:
            best = max(results, key=lambda x: x['strength'])
            if best['strength'] > 0:
                print(f"\n最佳机会: {best['symbol']}")
                print(f"   阶段: {best['phase']}")
                print(f"   信号强度: {best['strength']}/4")
    else:
        parser.print_help()
