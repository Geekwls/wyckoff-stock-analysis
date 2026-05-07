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
    """
    
    def __init__(self, box_size_pct: float = 1.0, reversal_boxes: int = 3):
        """
        Args:
            box_size_pct: 每个格子的价格百分比大小（默认1%）
            reversal_boxes: 反转所需的格子数（默认3格）
        """
        self.box_size_pct = box_size_pct / 100.0
        self.reversal_boxes = reversal_boxes
    
    def calculate_pnf(self, data: pd.DataFrame) -> Dict:
        """
        计算点数图数据
        
        Args:
            data: 包含OHLCV的DataFrame
            
        Returns:
            点数图分析结果
        """
        if data is None or len(data) < 20:
            return {'columns': [], 'horizontal_count': 0}
        
        closes = data['Close'].values
        highs = data['High'].values
        lows = data['Low'].values
        
        # 初始化第一个格子
        current_box = self._get_box_level(closes[0])
        direction = 'up'  # 'up' for X, 'down' for O
        
        columns = []
        current_column = {
            'direction': direction,
            'start_idx': 0,
            'start_price': closes[0],
            'boxes': [current_box],
            'high': current_box,
            'low': current_box
        }
        
        for i in range(1, len(closes)):
            price = closes[i]
            high = highs[i]
            low = lows[i]
            new_box = self._get_box_level(price)
            
            if direction == 'up':
                # 当前是X列（上涨）
                if new_box > current_box:
                    # 继续上涨
                    current_column['boxes'].append(new_box)
                    current_column['high'] = new_box
                    current_column['end_idx'] = i
                    current_box = new_box
                elif self._check_reversal_down(current_box, low):
                    # 反转为O列
                    columns.append(current_column)
                    direction = 'down'
                    reversal_box = current_box - self.reversal_boxes * self._get_box_size(current_box)
                    current_column = {
                        'direction': 'down',
                        'start_idx': i,
                        'start_price': price,
                        'boxes': [reversal_box],
                        'high': reversal_box,
                        'low': reversal_box
                    }
                    current_box = reversal_box
            else:
                # 当前是O列（下跌）
                if new_box < current_box:
                    # 继续下跌
                    current_column['boxes'].append(new_box)
                    current_column['low'] = new_box
                    current_column['end_idx'] = i
                    current_box = new_box
                elif self._check_reversal_up(current_box, high):
                    # 反转为X列
                    columns.append(current_column)
                    direction = 'up'
                    reversal_box = current_box + self.reversal_boxes * self._get_box_size(current_box)
                    current_column = {
                        'direction': 'up',
                        'start_idx': i,
                        'start_price': price,
                        'boxes': [reversal_box],
                        'high': reversal_box,
                        'low': reversal_box
                    }
                    current_box = reversal_box
        
        # 添加最后一列
        columns.append(current_column)
        
        return {
            'columns': columns,
            'total_columns': len(columns)
        }
    
    def calculate_horizontal_count(self, pnf_data: Dict, 
                                   accumulation_start: int = None,
                                   accumulation_end: int = None,
                                   phase: str = '',
                                   known_tr_high: float = None,
                                   known_tr_low: float = None,
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
            
        Returns:
            水平计数结果和目标价
        """
        columns = pnf_data.get('columns', [])
        if not columns:
            return {'count': 0, 'targets': {}}
        
        if known_tr_high is not None and known_tr_low is not None:
            accumulation_columns = [
                col for col in columns
                if col['low'] <= known_tr_high and col['high'] >= known_tr_low
            ]
            if not accumulation_columns:
                accumulation_columns = columns[-20:]
            method = "known_tr"
        elif accumulation_start is None or accumulation_end is None:
            accumulation_start, accumulation_end = self._find_accumulation_range(columns)
            if accumulation_start >= accumulation_end:
                return {'count': 0, 'targets': {}}
            accumulation_columns = columns[accumulation_start:accumulation_end + 1]
            method = "auto_detect"
        else:
            if accumulation_start >= accumulation_end:
                return {'count': 0, 'targets': {}}
            accumulation_columns = columns[accumulation_start:accumulation_end + 1]
            method = "explicit_index"
        
        horizontal_count = len(accumulation_columns)
        
        if horizontal_count < 3:
            return {'count': horizontal_count, 'targets': {}}
        
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
                'target_1': round(dist_base - base_effect * 0.618, 2),
                'target_2': round(dist_base - base_effect, 2),
                'target_3': round(dist_base - base_effect * 1.618, 2),
                'full_target': round(dist_base - base_effect * 2.0, 2)
            }
            base_price = dist_base
            breakout_direction = 'down'
            direction_note = '派发期因果法则：水平准备触发下跌目标'
        else:
            # 吸筹期或上涨趋势：使用原始方向
            if breakout_direction == 'up':
                acc_base = known_tr_high if known_tr_high is not None else accumulation_high
                targets = {
                    'target_1': round(acc_base + base_effect * 0.618, 2),
                    'target_2': round(acc_base + base_effect, 2),
                    'target_3': round(acc_base + base_effect * 1.618, 2),
                    'full_target': round(acc_base + base_effect * 2.0, 2)
                }
                base_price = acc_base
                direction_note = '吸筹期因果法则：水平准备触发上涨目标'
            else:
                dist_base = known_tr_low if known_tr_low is not None else accumulation_low
                targets = {
                    'target_1': round(dist_base - base_effect * 0.618, 2),
                    'target_2': round(dist_base - base_effect, 2),
                    'target_3': round(dist_base - base_effect * 1.618, 2),
                    'full_target': round(dist_base - base_effect * 2.0, 2)
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
            'base_effect': round(base_effect, 2),
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
        return round(int(price / box_size) * box_size, 2)
    
    def _get_box_size(self, price: float) -> float:
        """获取箱体大小（可根据价格区间调整）"""
        # 对于A股，使用固定百分比
        return round(price * self.box_size_pct, 2)
    
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
    pnf_data = calculator.calculate_pnf(data)
    result = calculator.calculate_horizontal_count(
        pnf_data, phase=phase,
        known_tr_high=known_tr_high, known_tr_low=known_tr_low
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
