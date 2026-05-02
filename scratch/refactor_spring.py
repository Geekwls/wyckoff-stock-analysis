import sys

def refactor():
    with open('tools/core/pattern_detector.py', 'r', encoding='utf-8') as f:
        content = f.read()

    old_method = '''    def _detect_spring_impl(self, lookback: int = None) -> Dict:
        """
        Spring检测核心实现
        """
        lookback = lookback or self.config.spring_lookback
        """
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
        
        # 交易区间幅度应该小于阈值
        if tr_range_pct > self.config.spring_range_threshold:
            return {'detected': False, 'reason': 'no_trading_range'}
        
        # 步骤2：确认支撑位（交易区间下边界）
        support_level = tr_low
        
        # 获取股性波动率分类
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.03, 'medium': 0.04, 'high': 0.05}
        max_breakdown_pct = threshold_map.get(volatility_class, 0.04)
        
        # 步骤3：向量化寻找跌破支撑的情况（优化性能）
        search_df = df.iloc[max(0, len(df) - 45):].copy()

        # 向量化计算：识别跌破支撑位的K线
        breakdown_mask = (
            (search_df['Low'] < support_level) &
            (search_df['Low'] >= support_level * (1 - max_breakdown_pct))
        )

        if not breakdown_mask.any():
            return {'detected': False, 'reason': 'no_breakdown_found'}

        # 向量化计算：收盘价位置和成交量比率
        search_df = search_df.copy()
        search_df['close_above_support'] = search_df['Close'] >= support_level
        search_df['vol_ma'] = search_df['Volume_MA20'].fillna(search_df['Volume'].mean())
        search_df['breakdown_vol_ratio'] = search_df['Volume'] / search_df['vol_ma']
        search_df['daily_range'] = search_df['High'] - search_df['Low']
        search_df['close_position'] = (
            (search_df['Close'] - search_df['Low']) / search_df['daily_range']
        ).fillna(1.0)

        # 向量化检查未来恢复情况（使用rolling和shift）
        recovery_days = self.config.spring_max_recovery_days
        recovery_info = []

        for day_offset in range(recovery_days + 1):
            if day_offset == 0:
                # 当天恢复
                future_mask = search_df['close_above_support']
            else:
                # 未来day_offset天内恢复
                future_close = search_df['Close'].shift(-day_offset)
                future_mask = future_close > support_level

            recovery_info.append({
                'day_offset': day_offset,
                'recovery_mask': future_mask,
                'recovery_close': search_df['Close'].shift(-day_offset),
                'recovery_high': search_df['High'].shift(-day_offset),
                'recovery_low': search_df['Low'].shift(-day_offset),
                'recovery_vol': search_df['Volume'].shift(-day_offset)
            })

        # 找到每个跌破点的最早恢复日
        springs = []
        seen_dates = set()

        breakdown_indices = search_df[breakdown_mask].index

        for idx in breakdown_indices:
            date_key = idx.strftime('%Y-%m-%d')
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            row_idx = search_df.index.get_loc(idx)
            current_low = search_df.loc[idx, 'Low']
            current_close = search_df.loc[idx, 'Close']
            current_vol = search_df.loc[idx, 'Volume']
            vol_ma = search_df.loc[idx, 'vol_ma']

            # 检查恢复情况
            recovery_found = False
            recovery_day = 0
            recovery_close = current_close
            recovery_high = search_df.loc[idx, 'High']
            recovery_low = current_low
            recovery_vol = current_vol

            close_above_support = search_df.loc[idx, 'close_above_support']

            if close_above_support:
                recovery_found = True
            else:
                for recovery in recovery_info[1:]:  # 跳过第0个（当天）
                    if row_idx < len(search_df) and recovery['recovery_mask'].iloc[row_idx]:
                        recovery_found = True
                        recovery_day = recovery['day_offset']
                        recovery_close = recovery['recovery_close'].iloc[row_idx]
                        recovery_high = recovery['recovery_high'].iloc[row_idx]
                        recovery_low = recovery['recovery_low'].iloc[row_idx]
                        recovery_vol = recovery['recovery_vol'].iloc[row_idx]
                        break

            if not recovery_found:
                continue

            # 收盘位置验证
            daily_range = recovery_high - recovery_low
            if daily_range > 0:
                close_position = (recovery_close - recovery_low) / daily_range
            else:
                close_position = 1.0 if recovery_close >= support_level else 0.0

            if not (recovery_close >= support_level or close_position >= 0.5):
                continue

            # 成交量模式验证
            breakdown_vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
            recovery_vol_ratio = recovery_vol / vol_ma if vol_ma > 0 else 1

            vol_pattern = 'neutral'
            if breakdown_vol_ratio < 0.8 and recovery_vol_ratio > 1.2:
                vol_pattern = 'bullish'
            elif breakdown_vol_ratio < 1.0 and recovery_vol_ratio > 1.0:
                vol_pattern = 'mildly_bullish'
            elif breakdown_vol_ratio > 1.5:
                vol_pattern = 'bearish'

            # 综合判断
            is_spring = False
            confidence = 0

            if close_above_support and close_position >= 0.7:
                is_spring = True
                confidence = 0.85
            elif close_above_support:
                is_spring = True
                confidence = 0.75
            elif recovery_found and vol_pattern in ['bullish', 'mildly_bullish']:
                is_spring = True
                confidence = 0.65
            elif recovery_found and recovery_day <= 2:
                is_spring = True
                confidence = 0.5

            if is_spring:
                springs.append({
                    'date': idx,
                    'breakdown_price': current_low,
                    'support_level': support_level,
                    'recovery_day': recovery_day,
                    'recovery_price': recovery_close,
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
        return {'detected': False, 'reason': 'no_spring_found'}'''

    new_method = '''    def _detect_spring_impl(self, lookback: int = None) -> Dict:
        """Spring检测核心实现 (已重构拆分)"""
        lookback = lookback or self.config.spring_lookback
        
        if self.data is None or len(self.data) < 30:
            return {'detected': False, 'reason': 'insufficient_data'}
            
        df = self.data.tail(lookback).copy()
        
        # 1. 检测交易区间前置条件
        support_level = self._check_spring_preconditions(df)
        if support_level is None:
            return {'detected': False, 'reason': 'no_trading_range'}
            
        # 2. 向量化寻找跌破情况和恢复信息
        search_df, breakdown_indices, recovery_info = self._find_spring_breakdowns(df, support_level)
        if breakdown_indices is None or len(breakdown_indices) == 0:
            return {'detected': False, 'reason': 'no_breakdown_found'}
            
        # 3. 逐个验证恢复情况
        springs = self._verify_spring_recoveries(search_df, breakdown_indices, support_level, recovery_info)
        
        if springs:
            return {'detected': True, 'signals': springs, 'latest_spring': springs[-1]}
        return {'detected': False, 'reason': 'no_spring_found'}

    def _check_spring_preconditions(self, df: pd.DataFrame) -> Optional[float]:
        """检测交易区间并返回支撑位（如果满足条件）"""
        tr_window = 60
        if len(df) < tr_window:
            return None
            
        tr_data = df.tail(tr_window)
        tr_high = tr_data['High'].max()
        tr_low = tr_data['Low'].min()
        tr_range_pct = (tr_high - tr_low) / tr_low
        
        if tr_range_pct > self.config.spring_range_threshold:
            return None
            
        return tr_low

    def _find_spring_breakdowns(self, df: pd.DataFrame, support_level: float) -> Tuple[pd.DataFrame, pd.Index, List[Dict]]:
        """寻找跌破点并预计算恢复掩码"""
        volatility_class = self._classify_volatility()
        threshold_map = {'low': 0.03, 'medium': 0.04, 'high': 0.05}
        max_breakdown_pct = threshold_map.get(volatility_class, 0.04)
        
        search_df = df.iloc[max(0, len(df) - 45):].copy()

        breakdown_mask = (
            (search_df['Low'] < support_level) &
            (search_df['Low'] >= support_level * (1 - max_breakdown_pct))
        )

        if not breakdown_mask.any():
            return search_df, None, []

        search_df['close_above_support'] = search_df['Close'] >= support_level
        search_df['vol_ma'] = search_df['Volume_MA20'].fillna(search_df['Volume'].mean())
        search_df['breakdown_vol_ratio'] = search_df['Volume'] / search_df['vol_ma']
        search_df['daily_range'] = search_df['High'] - search_df['Low']
        search_df['close_position'] = (
            (search_df['Close'] - search_df['Low']) / search_df['daily_range']
        ).fillna(1.0)

        recovery_days = self.config.spring_max_recovery_days
        recovery_info = []

        for day_offset in range(recovery_days + 1):
            if day_offset == 0:
                future_mask = search_df['close_above_support']
            else:
                future_close = search_df['Close'].shift(-day_offset)
                future_mask = future_close > support_level

            recovery_info.append({
                'day_offset': day_offset,
                'recovery_mask': future_mask,
                'recovery_close': search_df['Close'].shift(-day_offset),
                'recovery_high': search_df['High'].shift(-day_offset),
                'recovery_low': search_df['Low'].shift(-day_offset),
                'recovery_vol': search_df['Volume'].shift(-day_offset)
            })

        return search_df, search_df[breakdown_mask].index, recovery_info

    def _verify_spring_recoveries(self, search_df: pd.DataFrame, breakdown_indices: pd.Index, 
                                 support_level: float, recovery_info: List[Dict]) -> List[Dict]:
        """验证跌破点的恢复情况及成交量配合度"""
        springs = []
        seen_dates = set()

        for idx in breakdown_indices:
            date_key = idx.strftime('%Y-%m-%d')
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            row_idx = search_df.index.get_loc(idx)
            current_low = search_df.loc[idx, 'Low']
            current_close = search_df.loc[idx, 'Close']
            current_vol = search_df.loc[idx, 'Volume']
            vol_ma = search_df.loc[idx, 'vol_ma']

            recovery_found = False
            recovery_day = 0
            recovery_close = current_close
            recovery_high = search_df.loc[idx, 'High']
            recovery_low = current_low
            recovery_vol = current_vol

            close_above_support = search_df.loc[idx, 'close_above_support']

            if close_above_support:
                recovery_found = True
            else:
                for recovery in recovery_info[1:]:
                    if row_idx < len(search_df) and recovery['recovery_mask'].iloc[row_idx]:
                        recovery_found = True
                        recovery_day = recovery['day_offset']
                        recovery_close = recovery['recovery_close'].iloc[row_idx]
                        recovery_high = recovery['recovery_high'].iloc[row_idx]
                        recovery_low = recovery['recovery_low'].iloc[row_idx]
                        recovery_vol = recovery['recovery_vol'].iloc[row_idx]
                        break

            if not recovery_found:
                continue

            daily_range = recovery_high - recovery_low
            if daily_range > 0:
                close_position = (recovery_close - recovery_low) / daily_range
            else:
                close_position = 1.0 if recovery_close >= support_level else 0.0

            if not (recovery_close >= support_level or close_position >= 0.5):
                continue

            breakdown_vol_ratio = current_vol / vol_ma if vol_ma > 0 else 1
            recovery_vol_ratio = recovery_vol / vol_ma if vol_ma > 0 else 1

            vol_pattern = 'neutral'
            if breakdown_vol_ratio < 0.8 and recovery_vol_ratio > 1.2:
                vol_pattern = 'bullish'
            elif breakdown_vol_ratio < 1.0 and recovery_vol_ratio > 1.0:
                vol_pattern = 'mildly_bullish'
            elif breakdown_vol_ratio > 1.5:
                vol_pattern = 'bearish'

            is_spring = False
            confidence = 0

            if close_above_support and close_position >= 0.7:
                is_spring, confidence = True, 0.85
            elif close_above_support:
                is_spring, confidence = True, 0.75
            elif recovery_found and vol_pattern in ['bullish', 'mildly_bullish']:
                is_spring, confidence = True, 0.65
            elif recovery_found and recovery_day <= 2:
                is_spring, confidence = True, 0.5

            if is_spring:
                springs.append({
                    'date': idx,
                    'breakdown_price': current_low,
                    'support_level': support_level,
                    'recovery_day': recovery_day,
                    'recovery_price': recovery_close,
                    'close_above_support': close_above_support,
                    'vol_pattern': vol_pattern,
                    'breakdown_volume': current_vol,
                    'recovery_volume': recovery_vol,
                    'volume_ma': vol_ma,
                    'confidence': confidence,
                    'price': current_low
                })
        return springs'''

    if old_method in content:
        content = content.replace(old_method, new_method)
        with open('tools/core/pattern_detector.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("Success")
    else:
        print("Old method not found. Check exact formatting.")

if __name__ == '__main__':
    refactor()
