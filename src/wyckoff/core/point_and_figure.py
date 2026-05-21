"""
点数图 (Point & Figure) 模块
用于实现威科夫因果法则的正确计算方法
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class PointAndFigureCalculator:
    """
    点数图计算器

    威科夫因果法则的核心：
    - 因（Cause）：水平准备（横向盘整的规模，用列数衡量）
    - 果（Effect）：垂直运动（价格突破后的目标幅度）

    点数图通过X列（盘整宽度）来预测Y轴（价格目标）的高度

    孟洪涛原则：根据市场波动率动态调整PNF水平计数阈值
    """

    def __init__(self, box_size_pct: float = 1.0, reversal_boxes: int = 3):
        """
        Args:
            box_size_pct: 每个格子的价格百分比大小（默认1%）
            reversal_boxes: 反转所需的格子数（默认3格）
        """
        self.box_size_pct = box_size_pct / 100.0
        self.reversal_boxes = reversal_boxes

    def _round_by_step(self, value: float, step: float) -> float:
        """根据格宽自适应选择保留小数位数，防止精度丢失和舍入为0"""
        if step < 0.01:
            rounded = round(value, 5)
            return rounded if rounded != 0 else value
        elif step < 0.1:
            return round(value, 4)
        else:
            return round(value, 2)

    def get_dynamic_pnf_threshold(self, data: pd.DataFrame) -> int:
        """
        孟洪涛原则：根据市场波动率动态调整PNF水平计数阈值

        高波动市场：降低阈值（2列）- 避免错过信号
        低波动市场：提高阈值（4列）- 减少假信号
        正常波动：保持默认（3列）

        Returns:
            动态阈值 (2-4)
        """
        if data is None or len(data) < 20:
            return 3  # 默认阈值

        # 计算ATR百分比作为波动率度量
        atr_series = self._calculate_atr_series(data, 14)
        atr_pct = (atr_series.iloc[-1] / data['Close'].iloc[-1] * 100) if data['Close'].iloc[-1] > 0 else 0

        # 计算价格区间的波动率
        recent_high = data['High'].tail(20).max()
        recent_low = data['Low'].tail(20).min()
        range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0

        # 综合波动率评分
        volatility_score = (atr_pct + range_pct) / 2

        # 根据波动率返回动态阈值
        if volatility_score > 4.0:
            return 2  # 高波动市场：降低阈值
        elif volatility_score > 2.5:
            return 3  # 中高波动市场：正常阈值
        elif volatility_score < 1.5:
            return 4  # 低波动市场：提高阈值
        else:
            return 3  # 正常波动：默认阈值

    def _calculate_atr_series(self, data: pd.DataFrame, period: int = 14):
        """计算ATR序列"""
        high = data['High']
        low = data['Low']
        close = data['Close'].shift(1)

        tr1 = high - low
        tr2 = (high - close).abs()
        tr3 = (low - close).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()
    
    def calculate_pnf(self, data: pd.DataFrame) -> Dict:
        """
        计算点数图数据（使用 High/Low 逐笔构造）

        传统 PnF 方法：每根 K 线，在 X 列中尝试向上画到 High，
        在 O 列中尝试向下画到 Low。仅当无法沿当前方向前进时
        才检查三格反转。

        Args:
            data: 包含OHLCV的DataFrame

        Returns:
            点数图分析结果
        """
        if data is None or len(data) < 20:
            return {'columns': [], 'horizontal_count': 0}

        highs = data['High'].values
        lows = data['Low'].values

        # 初始化：用第一根 K 线的 midpoint 决定初始箱体
        mid = (highs[0] + lows[0]) / 2.0
        current_box = self._get_box_level(mid)
        direction = 'up'

        columns = []
        current_column = {
            'direction': direction,
            'start_idx': 0,
            'boxes': [current_box],
            'high': current_box,
            'low': current_box,
        }

        for i in range(1, len(highs)):
            high = highs[i]
            low = lows[i]

            if direction == 'up':
                # 尝试向上画 X
                target_box = self._get_box_level(high)
                if target_box > current_column['high']:
                    self._add_boxes_up(current_column, current_column['high'], target_box)
                    current_column['high'] = target_box
                    current_box = target_box
                # 检查向下反转
                elif self._check_reversal_down(current_column['high'], low):
                    rev_level = current_column['high'] - self.reversal_boxes * self._get_box_size(current_column['high'])
                    rev_box = self._get_box_level(rev_level)
                    columns.append(current_column)
                    direction = 'down'
                    current_column = {
                        'direction': 'down',
                        'start_idx': i,
                        'boxes': [rev_box],
                        'high': rev_box,
                        'low': rev_box,
                    }
                    current_box = rev_box
            else:
                # 尝试向下画 O
                target_box = self._get_box_level(low)
                if target_box < current_column['low']:
                    self._add_boxes_down(current_column, current_column['low'], target_box)
                    current_column['low'] = target_box
                    current_box = target_box
                # 检查向上反转
                elif self._check_reversal_up(current_column['low'], high):
                    rev_level = current_column['low'] + self.reversal_boxes * self._get_box_size(current_column['low'])
                    rev_box = self._get_box_level(rev_level)
                    columns.append(current_column)
                    direction = 'up'
                    current_column = {
                        'direction': 'up',
                        'start_idx': i,
                        'boxes': [rev_box],
                        'high': rev_box,
                        'low': rev_box,
                    }
                    current_box = rev_box

        columns.append(current_column)

        return {
            'columns': columns,
            'total_columns': len(columns),
        }

    def _add_boxes_up(self, col: Dict, from_box: float, to_box: float) -> None:
        """在 X 列中追加从 from_box 到 to_box 的中间箱体"""
        step = self._get_box_size(from_box)
        cur = from_box + step
        # 🔧 v1.3升级：使用格宽百分比自适应容差，替代硬编码的0.001以兼容高价股和极低价股
        tolerance = step * 0.01
        while cur <= to_box - tolerance:
            col['boxes'].append(self._round_by_step(cur, step))
            cur += step

    def _add_boxes_down(self, col: Dict, from_box: float, to_box: float) -> None:
        """在 O 列中追加从 from_box 到 to_box 的中间箱体"""
        step = self._get_box_size(from_box)
        cur = from_box - step
        # 🔧 v1.3升级：使用格宽百分比自适应容差
        tolerance = step * 0.01
        while cur >= to_box + tolerance:
            col['boxes'].append(self._round_by_step(cur, step))
            cur -= step
    
    def calculate_horizontal_count(self, pnf_data: Dict, 
                                   accumulation_start: int = None,
                                   accumulation_end: int = None,
                                   phase: str = '',
                                   known_tr_high: float = None,
                                   known_tr_low: float = None,
                                   data: pd.DataFrame = None,
                                   **kwargs) -> Dict:
        """
        计算水平计数（威科夫因果法则的核心）
        
        重要理论约束：
        - 派发期的"因"触发向下的"果"
        - 吸筹期的"因"触发向上的"果"
        
        Args:
            pnf_data: 点数图数据
            accumulation_start: 积累区开始列索引
            accumulation_end: 积累区结束列索引
            phase: 当前阶段（用于确定目标方向）
            known_tr_high: 已知交易区间上沿（如BC高点），优先使用
            known_tr_low: 已知交易区间下沿（如AR低点），优先使用
            data: 原始 OHLCV DataFrame
            
        Returns:
            水平计数结果和目标价
        """
        columns = pnf_data.get('columns', [])
        if not columns:
            return {'count': 0, 'targets': {}}
        
        if known_tr_high is not None and known_tr_low is not None:
            accumulation_columns_with_idx = [
                (col, i) for i, col in enumerate(columns)
                if col['low'] <= known_tr_high and col['high'] >= known_tr_low
            ]
            if not accumulation_columns_with_idx:
                accumulation_columns_with_idx = [(col, i) for i, col in enumerate(columns[-20:])]
            method = "known_tr"
        elif accumulation_start is None or accumulation_end is None:
            accumulation_start, accumulation_end = self._find_accumulation_range(columns)
            if accumulation_start >= accumulation_end:
                return {'count': 0, 'targets': {}}
            accumulation_columns_with_idx = [(columns[i], i) for i in range(accumulation_start, accumulation_end + 1)]
            method = "auto_detect"
        else:
            if accumulation_start >= accumulation_end:
                return {'count': 0, 'targets': {}}
            accumulation_columns_with_idx = [(columns[i], i) for i in range(accumulation_start, accumulation_end + 1)]
            method = "explicit_index"
        
        # ── PnF 最大密集线 (Count Line) 筹码重心计数 ──
        price_volume = {}
        for col, i in accumulation_columns_with_idx:
            # 1. 确定该列对应的原始 K 线成交量
            if data is not None and not data.empty:
                start_idx = col['start_idx']
                end_idx = columns[i + 1]['start_idx'] if i + 1 < len(columns) else len(data)
                col_vol = float(data.iloc[start_idx:end_idx]['Volume'].sum())
            else:
                col_vol = 1.0

            # 2. 确定该列包含的所有格子
            step = self._get_box_size(col['low'])
            boxes = []
            cur = col['low']
            while cur <= col['high'] + step * 0.01:
                boxes.append(self._round_by_step(cur, step))
                cur += step

            # 3. 将成交量平均分给所有格子
            if boxes:
                box_vol = col_vol / len(boxes)
                for b in boxes:
                    price_volume[b] = price_volume.get(b, 0.0) + box_vol

        # 4. 找到加权得分最高的价格水平线 (Count Line)
        if price_volume:
            best_price = max(price_volume, key=price_volume.get)
        else:
            all_highs = [col['high'] for col, _ in accumulation_columns_with_idx]
            all_lows = [col['low'] for col, _ in accumulation_columns_with_idx]
            best_price = (max(all_highs) + min(all_lows)) / 2.0 if all_highs else 0.0

        # 5. 过滤出与最大密集线重叠的列
        dense_columns = []
        for col, _ in accumulation_columns_with_idx:
            step = self._get_box_size(col['low'])
            if col['low'] - step * 0.01 <= best_price <= col['high'] + step * 0.01:
                dense_columns.append(col)

        # 6. 水平计数为与最大密集线重叠的真实列数
        horizontal_count = len(dense_columns)
        accumulation_columns = [col for col, _ in accumulation_columns_with_idx]

        # 孟洪涛原则：使用动态阈值（需要传入 data 参数）
        # 这里使用默认阈值3，调用方可以通过 kwargs 传入 dynamic_threshold
        min_threshold = kwargs.get('dynamic_threshold', 3)

        if horizontal_count < min_threshold:
            return {
                'count': horizontal_count,
                'targets': {},
                '_threshold_used': min_threshold,
                '_threshold_note': f'水平计数{horizontal_count}列 < 阈值{min_threshold}列（孟洪涛原则）'
            }
        
        # 计算积累区的价格范围
        all_highs = [col['high'] for col in accumulation_columns]
        all_lows = [col['low'] for col in accumulation_columns]
        accumulation_high = max(all_highs)
        accumulation_low = min(all_lows)
        
        # 获取箱体大小
        box_size = self._get_box_size(accumulation_high)
        
        # 计算垂直计数（价格范围内的箱体数，仅用于参考）
        vertical_count = int((accumulation_high - accumulation_low) / box_size) + 1
        
        # 威科夫因果法则核心公式：水平计数 × 箱体大小 = 目标幅度
        # 每1列盘整 = 1格箱体的价格推动力
        base_effect = horizontal_count * box_size
        
        # 确定突破方向（基于最后一列的方向）
        last_column = columns[-1] if columns else None
        breakout_direction = 'up' if last_column and last_column['direction'] == 'up' else 'down'
        
        # 关键修复：根据阶段调整目标方向
        # 派发期的"因"触发向下的"果"
        # 吸筹期的"因"触发向上的"果"
        is_distribution = 'distribution' in phase.lower() or '派发' in phase
        
        if is_distribution:
            # 派发期：目标从已知TR下沿或积累区下沿开始投射
            dist_base = known_tr_low if known_tr_low is not None else accumulation_low
            targets = {
                'target_1': self._round_by_step(dist_base - base_effect * 1.0, box_size),
                'target_2': self._round_by_step(dist_base - base_effect * 1.618, box_size),
                'target_3': self._round_by_step(dist_base - base_effect * 2.618, box_size),
                'full_target': self._round_by_step(dist_base - base_effect * 3.0, box_size)
            }
            base_price = dist_base
            breakout_direction = 'down'
            direction_note = '派发期因果法则：水平准备触发下跌目标'
        else:
            # 吸筹期或上涨趋势：使用原始方向
            if breakout_direction == 'up':
                acc_base = known_tr_high if known_tr_high is not None else accumulation_high
                targets = {
                    'target_1': self._round_by_step(acc_base + base_effect * 1.0, box_size),
                    'target_2': self._round_by_step(acc_base + base_effect * 1.618, box_size),
                    'target_3': self._round_by_step(acc_base + base_effect * 2.618, box_size),
                    'full_target': self._round_by_step(acc_base + base_effect * 3.0, box_size)
                }
                base_price = acc_base
                direction_note = '吸筹期因果法则：水平准备触发上涨目标'
            else:
                dist_base = known_tr_low if known_tr_low is not None else accumulation_low
                targets = {
                    'target_1': self._round_by_step(dist_base - base_effect * 1.0, box_size),
                    'target_2': self._round_by_step(dist_base - base_effect * 1.618, box_size),
                    'target_3': self._round_by_step(dist_base - base_effect * 2.618, box_size),
                    'full_target': self._round_by_step(dist_base - base_effect * 3.0, box_size)
                }
                base_price = dist_base
                direction_note = '吸筹期因果法则：水平准备触发下跌目标'
        
        return {
            'horizontal_count': horizontal_count,
            'vertical_count': vertical_count,
            'accumulation_range': {
                'high': accumulation_high,
                'low': accumulation_low,
                'columns': horizontal_count
            },
            'base_effect': self._round_by_step(base_effect, box_size),
            'breakout_direction': breakout_direction,
            'base_price': base_price,
            'targets': targets,
            'phase': phase,
            'direction_note': direction_note,
            'is_distribution': is_distribution,
            '_pnf_method': method,
        }
    
    def _get_box_level(self, price: float) -> float:
        """获取价格所在的箱体水平"""
        box_size = self._get_box_size(price)
        if box_size <= 0:
            box_size = 0.01
        
        level = int(price / box_size) * box_size
        # 🔧 v1.3升级：根据箱体格宽自适应四舍五入保留位数，防止低价仙股被强制截断导致除零/精度丢失
        return self._round_by_step(level, box_size)
    
    def _get_box_size(self, price: float) -> float:
        """获取箱体大小（可根据价格区间调整）"""
        # 对于A股，使用固定百分比
        size = price * self.box_size_pct
        if size <= 0:
            return 0.01
            
        # 🔧 v1.3升级：使用自适应保留位算法，完美保障超低价和超高价股的浮点精度一致性
        return self._round_by_step(size, size)
    
    def _check_reversal_down(self, current_box: float, low: float) -> bool:
        """检查是否发生向下反转"""
        box_size = self._get_box_size(current_box)
        return low <= current_box - self.reversal_boxes * box_size
    
    def _check_reversal_up(self, current_box: float, high: float) -> bool:
        """检查是否发生向上反转"""
        box_size = self._get_box_size(current_box)
        return high >= current_box + self.reversal_boxes * box_size
    
    def _find_accumulation_range(self, columns: List[Dict]) -> Tuple[int, int]:
        """
        自动检测积累区（盘整区）
        
        积累区特征：
        - 多列交替（方向频繁变化）
        - 价格范围相对稳定
        - 优先选择靠近当前价格的最近盘整区（避免选中历史旧区间）
        """
        if len(columns) < 5:
            return 0, len(columns) - 1
        
        best_start = 0
        best_end = len(columns) - 1
        best_score = float('inf')
        
        window_size = max(5, len(columns) // 4)
        total_windows = len(columns) - window_size
        
        for i in range(total_windows):
            window = columns[i:i + window_size]
            
            # 计算窗口的价格范围
            highs = [col['high'] for col in window]
            lows = [col['low'] for col in window]
            price_range = max(highs) - min(lows)
            
            # 计算方向变化次数
            direction_changes = sum(1 for j in range(1, len(window)) 
                                    if window[j]['direction'] != window[j-1]['direction'])
            
            # 基础评分：价格范围小且方向变化多 = 好的积累区
            base_score = price_range / (direction_changes + 1)
            
            # 加入"就近优先"权重：越靠近当前（窗口索引越大）得分越低（越优先）
            # 使用二次衰减，让靠近末尾的区间显著优先
            recency_weight = ((total_windows - i) / total_windows) ** 2
            score = base_score * (1 + recency_weight * 3)
            
            if score < best_score:
                best_score = score
                best_start = i
                best_end = i + window_size - 1
        
        return best_start, best_end


def calculate_cause_effect_from_pnf(data: pd.DataFrame,
                                    box_size_pct: float = 1.0,
                                    reversal_boxes: int = 3,
                                    phase: str = '',
                                    known_tr_high: float = None,
                                    known_tr_low: float = None) -> Dict:
    """
    基于点数图计算威科夫因果效应（便捷函数）

    孟洪涛原则：使用动态阈值根据市场波动率调整

    重要理论约束：
    - 派发期的"因"触发向下的"果"
    - 吸筹期的"因"触发向上的"果"

    Args:
        data: OHLCV数据
        box_size_pct: 箱体大小百分比
        reversal_boxes: 反转箱体数
        phase: 当前阶段（用于确定目标方向）

    Returns:
        因果效应分析结果
    """
    calculator = PointAndFigureCalculator(box_size_pct, reversal_boxes)

    # 孟洪涛原则：获取动态PNF阈值
    dynamic_threshold = calculator.get_dynamic_pnf_threshold(data)

    pnf_data = calculator.calculate_pnf(data)
    result = calculator.calculate_horizontal_count(
        pnf_data, phase=phase,
        known_tr_high=known_tr_high, known_tr_low=known_tr_low,
        data=data,  # 传入原始 DataFrame
        dynamic_threshold=dynamic_threshold  # 传入动态阈值
    )
    
    pnf_method = result.get('_pnf_method', 'auto_detect')
    if known_tr_high is not None and known_tr_low is not None:
        method_label = 'point_and_figure_from_tr'
        targets = result.get('targets', {})
        direction = result.get('breakout_direction', 'up')
        if direction == 'down':
            desc_targets = f"若跌破 {known_tr_low:.2f}，第一目标 {targets.get('target_1', 0):.2f}，第二目标 {targets.get('target_2', 0):.2f}"
        else:
            desc_targets = f"若突破 {known_tr_high:.2f}，第一目标 {targets.get('target_1', 0):.2f}，第二目标 {targets.get('target_2', 0):.2f}"
        description = (
            f"基于当前TR（{known_tr_low:.2f}-{known_tr_high:.2f}）内的点数图水平计数："
            f"{result.get('horizontal_count', 0)}列 × 箱体大小{box_size_pct:.0f}% = "
            f"目标幅度{result.get('base_effect', 0):.2f}。{desc_targets}"
        )
    else:
        method_label = 'point_and_figure'
        description = (
            f"基于点数图水平计数：积累区{result.get('horizontal_count', 0)}列 × "
            f"箱体大小{box_size_pct:.0f}% = "
            f"目标幅度{result.get('base_effect', 0):.2f}"
        )
    
    return {
        'method': method_label,
        'box_size_pct': box_size_pct,
        'reversal_boxes': reversal_boxes,
        'total_columns': pnf_data.get('total_columns', 0),
        'horizontal_count': result.get('horizontal_count', 0),
        'vertical_count': result.get('vertical_count', 0),
        'accumulation_range': result.get('accumulation_range', {}),
        'base_effect': result.get('base_effect', 0),
        'breakout_direction': result.get('breakout_direction', 'up'),
        'targets': result.get('targets', {}),
        'description': description,
        '_pnf_method': pnf_method,
    }
