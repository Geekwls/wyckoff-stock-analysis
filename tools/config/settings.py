from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Dict

class WyckoffConfig(BaseModel):
    """威科夫分析配置（带验证）"""
    confidence_threshold: float = Field(0.85, ge=0.0, le=1.0)
    min_data_length: int = Field(60, ge=20, le=1000)
    atr_period: int = Field(14, ge=5, le=50)
    atr_multiplier: float = Field(1.5, ge=0.5, le=5.0)
    volume_ma_period: int = Field(20, ge=5, le=100)
    
    # Spring检测参数
    spring_lookback: int = Field(120, ge=30, le=252)
    spring_max_recovery_days: int = Field(3, ge=1, le=10)
    spring_range_threshold: float = Field(0.30, ge=0.1, le=0.5)
    
    climax_range_multiplier: float = Field(1.5, ge=1.0, le=5.0)
    
    # 突破搜索窗口 (Spring/Upthrust 搜索最后 M 根 K线)
    breakout_search_window: int = Field(5, ge=1, le=20)
    
    @field_validator('min_data_length')
    @classmethod
    def validate_data_length(cls, v):
        if v < 20:
            raise ValueError('数据长度至少20天')
        return v
    
    model_config = ConfigDict(
        env_prefix="WYCKOFF_",
        populate_by_name=True
    )

class ScoringConfig(BaseModel):
    """评分表显式配置"""
    vol_strong_weight: int = Field(3, description="成交量强力确认权重")
    vol_moderate_weight: int = Field(1, description="成交量温和配合权重")
    trend_alignment_weight: int = Field(3, description="多时间框架一致性权重")
    market_bullish_weight: int = Field(4, description="顺势大盘多头权重")
    market_bearish_weight: int = Field(4, description="顺势大盘空头权重")
    market_range_bonus: int = Field(2, description="震荡市固定加分")
    max_score: int = Field(10, description="名义最高分")
    
    # 阶段识别置信度权重 (Confidence, MA, Volume)
    phase_weights: Dict[str, float] = Field(
        default={'confidence': 0.5, 'ma': 0.3, 'vol': 0.2},
        description="阶段识别置信度权重"
    )

class PositionSizingConfig(BaseModel):
    """仓位管理详细配置"""
    max_aggressive_position: float = Field(0.20, description="激进型最高仓位 (20%)")
    max_moderate_position: float = Field(0.10, description="稳健型最高仓位 (10%)")
    max_conservative_position: float = Field(0.05, description="保守型最高仓位 (5%)")
    volatility_cap_threshold: float = Field(0.04, description="高波动阈值 (ATR/Price > 4%)")
    liquidity_min_volume_ma20: int = Field(1000000, description="最低流动性门槛 (20日均量)")

class WyckoffThresholds(BaseModel):
    """威科夫分析阈值集中配置"""
    
    # ── 波动率分类阈值 ──────────────────────────────────────
    VOLATILITY_THRESHOLDS: Dict[str, Dict[str, float]] = Field(
        default={
            'spring_breakdown': {'low': 0.03, 'medium': 0.04, 'high': 0.05},
            'upthrust_breakout': {'low': 0.03, 'medium': 0.04, 'high': 0.05},
            'sos_price_change': {'low': 0.02, 'medium': 0.03, 'high': 0.05},
            'sow_price_change': {'low': -0.02, 'medium': -0.03, 'high': -0.05},
        }
    )
    
    # 标准 SOS/SOW 价格变化阈值 (不分波动率时的默认值)
    SOS_PRICE_CHANGE_DEFAULT: float = Field(0.02)
    SOW_PRICE_CHANGE_DEFAULT: float = Field(-0.02)
    
    # ── 成交量确认阈值 ──────────────────────────────────────
    VOLUME_CONFIRMATION: Dict[str, float] = Field(
        default={'strong': 1.5, 'moderate': 1.2, 'weak': 0.8}
    )
    
    # ── 收盘位置确认 ──────────────────────────────────────
    CLOSE_POSITION_CONFIRMATION: float = Field(0.7)
    RECOVERY_DAYS: int = Field(3)
    
    # ── 新威科夫操盘法（孟洪涛）JOC 参数 ──────────────────────
    # JOC (Jump Across the Creek / 跃过小溪)
    JOC_CREEK_QUANTILE: float = Field(0.85, description="近期区间高点分位数（小溪阻力）")
    JOC_BODY_RATIO: float = Field(0.55, description="突破日实体占波幅最小比例")
    JOC_UPPER_SHADOW_RATIO: float = Field(0.25, description="上影线最大占波幅比例")
    JOC_VOLUME_RATIO: float = Field(1.5, description="突破日最小量比（相对20日均量）")
    JOC_TEST_BAND: float = Field(0.02, description="回测允许偏离小溪位的比例 (±2%)")
    JOC_TEST_VOL_RATIO: float = Field(0.85, description="回测日量能萎缩阈值（< 均量85%）")

    # ── FTI (Fall Through the Ice / 跌破冰层) 参数 ────────────
    FTI_ICE_QUANTILE: float = Field(0.15, description="近期区间低点分位数（冰层支撑）")
    FTI_BODY_RATIO: float = Field(0.55, description="跌破日实体占波幅最小比例")
    FTI_LOWER_SHADOW_RATIO: float = Field(0.25, description="下影线最大占波幅比例")
    FTI_VOLUME_RATIO: float = Field(1.5, description="跌破日最小量比")
    FTI_TEST_BAND: float = Field(0.02, description="回测允许偏离冰层位的比例 (±2%)")
    FTI_TEST_VOL_RATIO: float = Field(0.85, description="回测日量能萎缩阈值")

    # ── VSA (Volume Spread Analysis) 参数 ─────────────────────
    VSA_NO_SUPPLY_BODY_RATIO: float = Field(0.45, description="No Supply: 实体最大占波幅比")
    VSA_NO_SUPPLY_VOL_RATIO: float = Field(0.80, description="No Supply: 量能上限（<均量80%）")
    VSA_NO_SUPPLY_CLOSE_POS: float = Field(0.40, description="No Supply: 收盘最低位置")
    VSA_NO_DEMAND_BODY_RATIO: float = Field(0.45, description="No Demand: 实体最大占波幅比")
    VSA_NO_DEMAND_VOL_RATIO: float = Field(0.80, description="No Demand: 量能上限")
    VSA_NO_DEMAND_CLOSE_POS: float = Field(0.60, description="No Demand: 收盘最高位置")
    VSA_STOPPING_VOL_RATIO: float = Field(1.50, description="Stopping Volume: 量能下限")
    VSA_STOPPING_BODY_RATIO: float = Field(0.40, description="Stopping Volume: 实体最大占波幅比")
    VSA_STOPPING_CLOSE_POS: float = Field(0.45, description="Stopping Volume: 收盘最低位置")
    
    # ── 涨跌停判断 ──────────────────────────────────────
    LIMIT_UP_THRESHOLD: float = Field(0.095, description="涨停阈值")
    LIMIT_DOWN_THRESHOLD: float = Field(-0.095, description="跌停阈值")
    
    # ── 高级评分权重 ──────────────────────────────────────
    QUALITY_WEIGHTS: Dict[str, float] = Field(
        default={
            'volume_ratio': 0.3,
            'price_pct': 0.3,
            'confidence': 0.2,
            'confirmation': 0.2
        },
        description="信号质量分项权重"
    )
    TIME_DECAY_HALF_LIFE: int = Field(20, description="信号强度随时间衰减的半衰期（天）")
    CONFLICT_PENALTY: float = Field(30.0, description="多空冲突时的扣分")
    
    # ── 交易成本与滑点 ──────────────────────────────────
    COMMISSION_RATE: float = Field(0.0003, description="佣金率 (万三)")
    SLIPPAGE_RATE: float = Field(0.001, description="双边滑点 (10 BP)")
    IMPACT_COST_RATE: float = Field(0.0005, description="冲击成本 (5 BP)")
    
    # ── 评分与仓位配置 ──────────────────────────────────────
    SCORING: ScoringConfig = Field(default_factory=ScoringConfig)
    POSITION_SIZING: PositionSizingConfig = Field(default_factory=PositionSizingConfig)
    
    def get_volatility_threshold(self, threshold_type: str, volatility_class: str) -> float:
        """
        获取波动率阈值
        
        Args:
            threshold_type: 阈值类型（如 'spring_breakdown', 'sos_price_change'）
            volatility_class: 波动率分类（'low', 'medium', 'high'）
            
        Returns:
            对应的阈值
        """
        thresholds = self.VOLATILITY_THRESHOLDS.get(threshold_type, {})
        return thresholds.get(volatility_class, 0.035)
