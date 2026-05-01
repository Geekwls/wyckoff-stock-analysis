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

    def detect_spring(self, lookback: int = 20) -> Dict:
        """检测Spring（震仓）"""
        if self.data is None or len(self.data) < lookback + 10:
            return {}

        df = self.data.tail(lookback + 10).copy()
        springs = []

        for i in range(10, len(df)):
            current_low = df['Low'].iloc[i]
            current_close = df['Close'].iloc[i]

            past_lows = df['Low'].iloc[i-20:i]
            support_level = past_lows.min()

            if current_low < support_level * 0.98:
                future_data = df.iloc[i:min(i+5, len(df))]
                future_high = future_data['High'].max()
                recovery_days = (future_data['High'].idxmax() - df.index[i]).days if len(future_data) > 1 else 0

                breakdown_vol = df['Volume'].iloc[i]
                recovery_vol = future_data['Volume'].mean()
                vol_ma = df['Volume_MA20'].iloc[i]

                is_spring = (
                    future_high > support_level * 1.02 and
                    recovery_days <= 3 and
                    recovery_vol > breakdown_vol * 1.2
                )

                if is_spring:
                    springs.append({
                        'date': df.index[i],
                        'breakdown_price': current_low,
                        'support_level': support_level,
                        'recovery_price': future_high,
                        'recovery_days': recovery_days,
                        'breakdown_volume': breakdown_vol,
                        'recovery_volume': recovery_vol,
                        'volume_ma': vol_ma
                    })

        if springs:
            return {'detected': True, 'springs': springs, 'latest_spring': springs[-1]}
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

    def identify_phase(self) -> str:
        """识别当前威科夫阶段"""
        if self.data is None:
            return "Unknown"

        tr_info = self.detect_trading_range()

        if not tr_info.get('is_consolidation'):
            ma20 = self.data['MA20'].iloc[-1]
            ma50 = self.data['MA50'].iloc[-1]
            ma200 = self.data['MA200'].iloc[-1]
            current = self.data['Close'].iloc[-1]

            if current > ma20 > ma50 > ma200:
                return "Markup Phase E (强势上涨)"
            elif current > ma20 > ma50 and ma20 < ma200:
                return "Accumulation Phase D (可能在建仓末期)"
            elif current < ma20 < ma50 < ma200:
                return "Markdown Phase E (强势下跌)"
            elif current < ma20 < ma50 and ma20 > ma200:
                return "Distribution Phase D (可能在出货末期)"
            else:
                return "Trending (趋势中)"
        else:
            position = tr_info['position']
            vol_trend = tr_info['volume_trend']

            if vol_trend == 'decreasing':
                if position < 0.3:
                    return "Accumulation Phase B/C (可能在建仓中)"
                elif position < 0.7:
                    return "Accumulation Phase C-D (可能在震仓)"
                else:
                    return "Accumulation Phase D-E (准备突破)"
            else:
                if position > 0.7:
                    return "Distribution Phase B/C (可能在出货中)"
                elif position > 0.3:
                    return "Distribution Phase C-D (可能在假突破)"
                else:
                    return "Distribution Phase D-E (准备跌破)"

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

    def generate_json(self) -> str:
        """生成JSON格式的分析报告（供AI Agent读取）"""
        if not self.fetch_data():
            return json.dumps({"error": f"无法获取数据: {self.symbol}"}, ensure_ascii=False)
            
        result = {
            "symbol": self.symbol,
            "date": datetime.now().strftime('%Y-%m-%d'),
            "phase": self.identify_phase(),
            "basic_data": {
                "current_price": round(self.data['Close'].iloc[-1], 2),
                "volume": int(self.data['Volume'].iloc[-1]),
                "volume_ratio": round(self.data['Volume'].iloc[-1] / self.data['Volume_MA20'].iloc[-1], 2)
            },
            "events": {
                "trading_range": self.detect_trading_range(),
                "spring": self.detect_spring(),
                "upthrust": self.detect_upthrust(),
                "sos": self.detect_sos(),
                "sow": self.detect_sow(),
                "lps": self.detect_lps(),
                "lpsy": self.detect_lpsy()
            },
            "cause_effect": self.calculate_cause_effect()
        }
        
        # 获取大盘基准
        index_symbol = self._get_baseline_index_symbol()
        idx_analyzer = WyckoffAnalyzer(index_symbol, self.period, self.config)
        import os, sys
        from contextlib import redirect_stdout
        with open(os.devnull, 'w') as f, redirect_stdout(f):
            idx_success = idx_analyzer.fetch_data()
            
        if idx_success:
            result["market_context"] = {
                "index_symbol": index_symbol,
                "phase": idx_analyzer.identify_phase()
            }
        else:
            result["market_context"] = {
                "index_symbol": index_symbol,
                "error": "无法获取大盘数据"
            }
            
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
