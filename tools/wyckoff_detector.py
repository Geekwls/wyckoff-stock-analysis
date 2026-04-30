#!/usr/bin/env python3
"""
威科夫形态自动识别工具
Wyckoff Pattern Automatic Detector

功能：
1. 识别积累/分布区间
2. 检测Spring/Upthrust
3. 标记SOS/SOW/LPS/LPSY
4. 批量扫描股票
5. 生成分析报告
"""

import yfinance as yf
import baostock as bs
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')


class WyckoffPatternDetector:
    """威科夫形态检测器"""

    def __init__(self, symbol: str, period: str = "1y"):
        """
        初始化检测器

        Args:
            symbol: 股票代码或中文名称
            period: 数据周期 (1y, 2y, 3y, 5y)
        """
        self.symbol = symbol
        self.period = period
        self.data = None
        self.signals = {}
        self.cache_file = os.path.join(os.path.dirname(__file__), "stock_cache.json")

    def _is_a_stock(self, symbol: str) -> bool:
        """判断是否为A股"""
        if symbol.isdigit():
            return True
        if symbol.endswith(('.SH', '.SZ')):
            return True
        return False

    def _resolve_stock_name(self, name: str) -> str:
        """中文名称 → 股票代码"""
        # 1. 查本地缓存
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if name in cache:
                    return cache[name]
            except Exception:
                pass
        
        # 2. baostock 实时查询
        code = self._search_from_baostock(name)
        
        if code:
            self._update_cache(name, code)
            return code
        
        return None

    def _search_from_baostock(self, keyword: str) -> str:
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
            print(f"baostock query failed: {e}")
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
            print(f"Cache update failed: {e}")

    def fetch_data(self) -> bool:
        """获取股票数据（自动识别市场）"""
        try:
            # 1. 中文名称解析为代码
            symbol = self.symbol
            if not symbol.replace('.', '').isdigit() and not symbol.isalpha():
                resolved = self._resolve_stock_name(symbol)
                if resolved:
                    symbol = resolved
                    self.symbol = symbol
                else:
                    print(f"❌ {self.symbol}: 无法识别股票名称")
                    return False
            
            # 2. 判断市场并获取数据
            if self._is_a_stock(symbol):
                return self._fetch_a_stock_data(symbol)
            else:
                return self._fetch_global_stock_data(symbol)

        except Exception as e:
            print(f"❌ {self.symbol}: 获取数据失败 - {str(e)}")
            return False

    def _fetch_a_stock_data(self, symbol: str) -> bool:
        """baostock 获取A股数据"""
        try:
            # 转换代码格式
            if '.' in symbol:
                parts = symbol.split('.')
                code = f"{parts[1].lower()}.{parts[0]}"
            else:
                prefix = 'sh' if symbol.startswith('6') else 'sz'
                code = f"{prefix}.{symbol}"
            
            # 计算日期范围
            end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
            period_days = {
                "1y": 365, "2y": 730, "3y": 1095, "5y": 1825
            }
            days = period_days.get(self.period, 365)
            start_date = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
            
            # 登录获取数据
            lg = bs.login()
            if lg.error_code != '0':
                print(f"❌ {symbol}: baostock 登录失败")
                return False
            
            rs = bs.query_history_k_data_plus(
                code,
                "date,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"
            )
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if not data_list or len(data_list) < 60:
                print(f"❌ {symbol}: 数据不足")
                return False
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            df = df.rename(columns={'date': 'Date', 'open': 'Open', 'high': 'High', 
                                   'low': 'Low', 'close': 'Close', 'volume': 'Volume'})
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            df = df.astype(float)
            
            self.data = df
            self._calculate_indicators()
            return True
            
        except Exception as e:
            print(f"❌ {symbol}: 获取A股数据失败 - {str(e)}")
            return False

    def _fetch_global_stock_data(self, symbol: str) -> bool:
        """yfinance 获取其他市场数据"""
        try:
            stock = yf.Ticker(symbol)
            self.data = stock.history(period=self.period)

            if self.data.empty or len(self.data) < 60:
                print(f"❌ {symbol}: 数据不足")
                return False

            self._calculate_indicators()
            return True

        except Exception as e:
            print(f"❌ {symbol}: 获取数据失败 - {str(e)}")
            return False

    def _calculate_indicators(self):
        """计算技术指标"""
        df = self.data.copy()

        # 移动平均线
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA50'] = df['Close'].rolling(window=50).mean()
        df['MA200'] = df['Close'].rolling(window=200).mean()

        # 成交量移动平均
        df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()

        # 价格变化率
        df['Change'] = df['Close'].pct_change()
        df['High_Low_Range'] = (df['High'] - df['Low']) / df['Close']

        # 波动率
        df['Volatility'] = df['Change'].rolling(window=20).std()

        self.data = df

    def detect_trading_range(self, window: int = 60) -> Dict:
        """
        检测交易区间（积累/分布）

        Args:
            window: 检测窗口（天数）

        Returns:
            交易区间信息
        """
        if self.data is None or len(self.data) < window:
            return {}

        df = self.data.tail(window).copy()

        # 计算价格波动范围
        high_max = df['High'].max()
        low_min = df['Low'].min()
        range_pct = (high_max - low_min) / low_min

        # 判断是否为横盘区间
        is_consolidation = range_pct < 0.3  # 30%以内算横盘

        # 成交量特征
        vol_trend = 'decreasing' if df['Volume'].iloc[-20:].mean() < df['Volume'].iloc[-60:-20].mean() else 'increasing'

        # 价格位置
        current_price = df['Close'].iloc[-1]
        position = (current_price - low_min) / (high_max - low_min)  # 0-1之间

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
        """
        检测Spring（震仓）

        Args:
            lookback: 回看天数

        Returns:
            Spring信息
        """
        if self.data is None or len(self.data) < lookback + 10:
            return {}

        df = self.data.tail(lookback + 10).copy()

        springs = []

        # 寻找跌破支撑的形态
        for i in range(10, len(df)):
            current_low = df['Low'].iloc[i]
            current_close = df['Close'].iloc[i]

            # 找到前期的支撑位（过去20天最低点）
            past_lows = df['Low'].iloc[i-20:i]
            support_level = past_lows.min()

            # 判断是否跌破支撑
            if current_low < support_level * 0.98:  # 跌破2%以上
                # 检查后续3-5天是否收回
                future_data = df.iloc[i:min(i+5, len(df))]

                # 找到后续最高价
                future_high = future_data['High'].max()
                recovery_days = (future_data['High'].idxmax() - df.index[i]).days

                # 成交量分析
                breakdown_vol = df['Volume'].iloc[i]
                recovery_vol = future_data['Volume'].mean()
                vol_ma = df['Volume_MA20'].iloc[i]

                # 判断是否为真Spring
                is_spring = (
                    future_high > support_level * 1.02 and  # 收到支撑上方2%
                    recovery_days <= 3 and  # 3天内收回
                    recovery_vol > breakdown_vol * 1.2  # 收回时放量
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
            return {
                'detected': True,
                'springs': springs,
                'latest_spring': springs[-1] if springs else None
            }

        return {'detected': False}

    def detect_upthrust(self, lookback: int = 20) -> Dict:
        """
        检测Upthrust（假突破）

        Args:
            lookback: 回看天数

        Returns:
            Upthrust信息
        """
        if self.data is None or len(self.data) < lookback + 10:
            return {}

        df = self.data.tail(lookback + 10).copy()

        upthrusts = []

        # 寻找突破阻力的形态
        for i in range(10, len(df)):
            current_high = df['High'].iloc[i]
            current_close = df['Close'].iloc[i]

            # 找到前期的阻力位（过去20天最高点）
            past_highs = df['High'].iloc[i-20:i]
            resistance_level = past_highs.max()

            # 判断是否突破阻力
            if current_high > resistance_level * 1.02:  # 突破2%以上
                # 检查后续3-5天是否回落
                future_data = df.iloc[i:min(i+5, len(df))]

                # 找到后续最低价
                future_low = future_data['Low'].min()
                rejection_days = (future_data['Low'].idxmin() - df.index[i]).days

                # 成交量分析
                breakout_vol = df['Volume'].iloc[i]
                rejection_vol = future_data['Volume'].mean()
                vol_ma = df['Volume_MA20'].iloc[i]

                # 收盘位置分析
                close_from_high = (current_high - current_close) / current_high

                # 判断是否为真Upthrust
                is_upthrust = (
                    future_low < resistance_level * 0.98 and  # 回落到阻力下方2%
                    rejection_days <= 3 and  # 3天内回落
                    close_from_high > 0.01 and  # 收盘距高点1%以上（上影线）
                    rejection_vol > breakout_vol * 1.2  # 落下时放量
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
            return {
                'detected': True,
                'upthrusts': upthrusts,
                'latest_upthrust': upthrusts[-1] if upthrusts else None
            }

        return {'detected': False}

    def detect_sos(self) -> Dict:
        """
        检测SOS（Sign of Strength - 强势信号）

        Returns:
            SOS信息
        """
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()

        # 寻找放量突破
        sos_signals = []

        for i in range(20, len(df)):
            current_close = df['Close'].iloc[i]
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]

            # 过去20天的阻力位
            past_high = df['High'].iloc[i-20:i].max()

            # 判断是否突破
            if current_close > past_high * 1.03:  # 突破3%以上
                # 成交量放大
                vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1

                # 价格涨幅
                price_change = (current_close - df['Close'].iloc[i-1]) / df['Close'].iloc[i-1]

                # 当日收盘位置
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_position = (current_close - df['Low'].iloc[i]) / daily_range if daily_range > 0 else 0.5

                # 判断是否为SOS
                is_sos = (
                    vol_ratio > 1.5 and  # 成交量1.5倍以上
                    price_change > 0.03 and  # 涨幅3%以上
                    close_position > 0.7  # 收盘在当日高位
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
            return {
                'detected': True,
                'signals': sos_signals,
                'latest': sos_signals[-1]
            }

        return {'detected': False}

    def detect_sow(self) -> Dict:
        """
        检测SOW（Sign of Weakness - 弱势信号）

        Returns:
            SOW信息
        """
        if self.data is None or len(self.data) < 60:
            return {}

        df = self.data.copy()

        # 寻找放量跌破
        sow_signals = []

        for i in range(20, len(df)):
            current_close = df['Close'].iloc[i]
            current_vol = df['Volume'].iloc[i]
            vol_ma = df['Volume_MA20'].iloc[i]

            # 过去20天的支撑位
            past_low = df['Low'].iloc[i-20:i].min()

            # 判断是否跌破
            if current_close < past_low * 0.97:  # 跌破3%以上
                # 成交量放大
                vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1

                # 价格跌幅
                price_change = (current_close - df['Close'].iloc[i-1]) / df['Close'].iloc[i-1]

                # 当日收盘位置
                daily_range = df['High'].iloc[i] - df['Low'].iloc[i]
                close_position = (df['High'].iloc[i] - current_close) / daily_range if daily_range > 0 else 0.5

                # 判断是否为SOW
                is_sow = (
                    vol_ratio > 1.5 and  # 成交量1.5倍以上
                    price_change < -0.03 and  # 跌幅3%以上
                    close_position > 0.7  # 收盘在当日低位
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
            return {
                'detected': True,
                'signals': sow_signals,
                'latest': sow_signals[-1]
            }

        return {'detected': False}

    def detect_lps(self, days_since_sos: int = 10) -> Dict:
        """
        检测LPS（Last Point of Support - 最后支撑点）

        Args:
            days_since_sos: SOS后的天数

        Returns:
            LPS信息
        """
        # 先找SOS
        sos_result = self.detect_sos()

        if not sos_result['detected']:
            return {'detected': False}

        latest_sos = sos_result['latest']
        sos_date = latest_sos['date']

        # 找到SOS之后的回调
        mask = self.data.index >= sos_date
        df_after_sos = self.data[mask].tail(days_since_sos)

        if len(df_after_sos) < 3:
            return {'detected': False}

        # 找到最低点（LPS候选）
        lps_idx = df_after_sos['Low'].idxmin()
        lps_price = df_after_sos['Low'].min()

        # 成交量比较
        lps_vol = df_after_sos.loc[lps_idx, 'Volume']
        sos_vol = latest_sos.get('volume_ratio', 1)

        # 判断是否为LPS
        is_lps = (
            lps_vol < sos_vol * 0.7 and  # 成交量缩小
            lps_price > latest_sos['breakthrough_level'] * 0.95  # 未跌破突破位太多
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
        """
        检测LPSY（Last Point of Supply - 最后供应点）

        Args:
            days_since_sow: SOW后的天数

        Returns:
            LPSY信息
        """
        # 先找SOW
        sow_result = self.detect_sow()

        if not sow_result['detected']:
            return {'detected': False}

        latest_sow = sow_result['latest']
        sow_date = latest_sow['date']

        # 找到SOW之后的反弹
        mask = self.data.index >= sow_date
        df_after_sow = self.data[mask].tail(days_since_sow)

        if len(df_after_sow) < 3:
            return {'detected': False}

        # 找到最高点（LPSY候选）
        lpsy_idx = df_after_sow['High'].idxmax()
        lpsy_price = df_after_sow['High'].max()

        # 成交量比较
        lpsy_vol = df_after_sow.loc[lpsy_idx, 'Volume']
        sow_vol = latest_sow.get('volume_ratio', 1)

        # 判断是否为LPSY
        is_lpsy = (
            lpsy_vol < sow_vol * 0.7 and  # 成交量缩小
            lpsy_price < latest_sow['breakdown_level'] * 1.05  # 未超过跌破位太多
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

    def identify_phase(self) -> str:
        """
        识别当前威科夫阶段

        Returns:
            阶段名称
        """
        if self.data is None:
            return "Unknown"

        # 检测交易区间
        tr_info = self.detect_trading_range()

        if not tr_info.get('is_consolidation'):
            # 判断趋势
        ma20 = self.data['MA20'].iloc[-1]
        ma50 = self.data['MA50'].iloc[-1]
        ma200 = self.data['MA200'].iloc[-1]
        current = self.data['Close'].iloc[-1]

        if current > ma20 > ma50 > ma200:
            return "Markup Phase E (强势上涨)"
        elif current > ma20 > ma50 but ma20 < ma200:
            return "Accumulation Phase D (可能在建仓末期)"
        elif current < ma20 < ma50 < ma200:
            return "Markdown Phase E (强势下跌)"
        elif current < ma20 < ma50 but ma20 > ma200:
            return "Distribution Phase D (可能在出货末期)"
        else:
            return "Trending (趋势中)"
        else:
            # 在横盘中，判断是积累还是分布
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

    def generate_report(self) -> str:
        """
        生成分析报告

        Returns:
            格式化的报告文本
        """
        if not self.fetch_data():
            return f"❌ {self.symbol}: 无法获取数据"

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

        # 交易区间
        if trading_range.get('is_consolidation'):
            report += f"""
✅ 检测到交易区间:
   区间: {trading_range['low']:.2f} - {trading_range['high']:.2f}
   幅度: {trading_range['range_pct']*100:.1f}%
   当前位置: {trading_range['position']*100:.0f}% (0%=底部, 100%=顶部)
   成交量趋势: {trading_range['volume_trend']}
"""

        # Spring
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

        # Upthrust
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

        # SOS
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

        # SOW
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

        # LPS
        if lps['detected']:
            report += f"""
✅ 检测到LPS（Last Point of Support）:
   日期: {lps['date'].strftime('%Y-%m-%d')}
   价格: {lps['price']:.2f}
   回调幅度: {lps['pullback_pct']*100:.1f}%
   成交量缩小: 是（{lps['volume']:.0f} vs SOS时期{lps['sos_volume']:.0f}）
   ⭐ 建议做多入场点
"""

        # LPSY
        if lpsy['detected']:
            report += f"""
✅ 检测到LPSY（Last Point of Supply）:
   日期: {lpsy['date'].strftime('%Y-%m-%d')}
   价格: {lpsy['price']:.2f}
   反弹幅度: {lpsy['rally_pct']*100:.1f}%
   成交量缩小: 是（{lpsy['volume']:.0f} vs SOW时期{lpsy['sow_volume']:.0f}）
   ⭐ 建议做空入场点
"""

        report += f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【交易建议】
"""

        # 生成交易建议
        if lps['detected'] and not lpsy['detected']:
            report += f"""
✅ 做多机会:
   入场价格: {lps['price']:.2f} (LPS)
   止损价格: {lps['price']*0.95:.2f} (保守)
   目标价格: 待定（需要因果测算）
   风险提示: 请设置好止损，严格执行
"""

        elif lpsy['detected'] and not lps['detected']:
            report += f"""
✅ 做空机会:
   入场价格: {lpsy['price']:.2f} (LPSY)
   止损价格: {lpsy['price']*1.05:.2f} (保守)
   目标价格: 待定（需要因果测算）
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
        print(f"🔍 扫描 {symbol}...")

        detector = WyckoffPatternDetector(symbol, period)

        if detector.fetch_data():
            phase = detector.identify_phase()

            # 检测关键信号
            signals = {
                'symbol': symbol,
                'phase': phase,
                'has_spring': detector.detect_spring()['detected'],
                'has_upthrust': detector.detect_upthrust()['detected'],
                'has_sos': detector.detect_sos()['detected'],
                'has_sow': detector.detect_sow()['detected'],
                'has_lps': detector.detect_lps()['detected'],
                'has_lpsy': detector.detect_lpsy()['detected'],
            }

            # 计算信号强度
            signal_strength = sum([
                signals['has_lps'],
                signals['has_lpsy'],
                signals['has_sos'],
                signals['has_sow']
            ])

            signals['strength'] = signal_strength
            results.append(signals)

            # 显示高信号股票
            if signal_strength >= 1:
                print(f"  ✅ {phase}")
                if signals['has_lps']:
                    print(f"     ⭐ 检测到LPS（做多机会）")
                if signals['has_lpsy']:
                    print(f"     ⭐ 检测到LPSY（做空机会）")
        else:
            print(f"  ❌ 获取数据失败")

    return results


# 命令行使用
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        symbol = sys.argv[1]
        detector = WyckoffPatternDetector(symbol)
        print(detector.generate_report())
    else:
        # 默认扫描示例
        symbols = ['AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOGL']
        print("📊 批量扫描美股示例...\n")
        results = batch_scan(symbols)

        print("\n📊 扫描完成！\n")
        print(f"总计扫描: {len(symbols)} 只股票")
        print(f"发现信号: {sum(1 for r in results if r['strength'] > 0)} 只")

        # 显示最佳机会
        if results:
            best = max(results, key=lambda x: x['strength'])
            if best['strength'] > 0:
                print(f"\n🎯 最佳机会: {best['symbol']}")
                print(f"   阶段: {best['phase']}")
                print(f"   信号强度: {best['strength']}/4")
