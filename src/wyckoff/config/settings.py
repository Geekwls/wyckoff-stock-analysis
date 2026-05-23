from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from typing import Dict, Annotated

class ScoringConfig(BaseModel):
    """评分表显式配置"""
    model_config = ConfigDict(extra='allow')
    vol_strong_weight: Annotated[int, Field(description="成交量强力确认权重")] = 3
    vol_moderate_weight: Annotated[int, Field(description="成交量温和配合权重")] = 1
    trend_alignment_weight: Annotated[int, Field(description="多时间框架一致性权重")] = 3
    market_bullish_weight: Annotated[int, Field(description="顺势大盘多头权重")] = 4
    market_bearish_weight: Annotated[int, Field(description="顺势大盘空头权重")] = 4
    market_range_bonus: Annotated[int, Field(description="震荡市固定加分")] = 2
    max_score: Annotated[int, Field(description="名义最高分")] = 10

    # 阶段识别置信度权重 (Confidence, MA, Volume)
    phase_weights: Annotated[Dict[str, float], Field(description="阶段识别置信度权重")] = {'confidence': 0.5, 'ma': 0.3, 'vol': 0.2}

class PositionSizingConfig(BaseModel):
    """仓位管理详细配置"""
    model_config = ConfigDict(extra='allow')
    max_aggressive_position: Annotated[float, Field(description="激进型最高仓位 (20%)")] = 0.20
    max_moderate_position: Annotated[float, Field(description="稳健型最高仓位 (10%)")] = 0.10
    max_conservative_position: Annotated[float, Field(description="保守型最高仓位 (5%)")] = 0.05
    volatility_cap_threshold: Annotated[float, Field(description="高波动阈值 (ATR/Price > 4%)")] = 0.04
    liquidity_min_volume_ma20: Annotated[int, Field(description="最低流动性门槛 (20日均量)")] = 1000000
    normal_position_pct: Annotated[float, Field(description="默认基准常规仓位百分比 (0-100)")] = 50.0

class WyckoffThresholds(BaseModel):
    """威科夫分析阈值集中配置"""
    market_type: Annotated[str, Field(description="市场类型（如 CRYPTO, A_SHARE）")] = "UNKNOWN"

    # ── 波动率分类阈值 ──────────────────────────────────────
    VOLATILITY_THRESHOLDS: Annotated[Dict[str, Dict[str, float]], Field(description="波动率分类阈值")] = {
        'spring_breakdown': {'low': 0.03, 'medium': 0.04, 'high': 0.05, 'extreme': 0.07},
        'upthrust_breakout': {'low': 0.03, 'medium': 0.04, 'high': 0.05, 'extreme': 0.07},
        'sos_price_change': {'low': 0.02, 'medium': 0.03, 'high': 0.05, 'extreme': 0.06},
        'sow_price_change': {'low': -0.02, 'medium': -0.03, 'high': -0.05, 'extreme': -0.06},
    }

    # ── 波动率百分比边界（百分比数值量纲，如1.5代表1.5%） ───────
    CRYPTO_VOL_BOUNDARIES: Annotated[Dict[str, float], Field(description="Crypto波动率定界百分比")] = {'low': 3.0, 'medium': 6.0, 'high': 10.0}
    DEFAULT_VOL_BOUNDARIES: Annotated[Dict[str, float], Field(description="普通市场波动率定界百分比")] = {'low': 1.5, 'medium': 3.0, 'high': 5.0}


    # 标准 SOS/SOW 价格变化阈值 (不分波动率时的默认值)
    SOS_PRICE_CHANGE_DEFAULT: Annotated[float, Field(description="标准 SOS 价格变化阈值")] = 0.02
    SOW_PRICE_CHANGE_DEFAULT: Annotated[float, Field(description="标准 SOW 价格变化阈值")] = -0.02

    # ── 成交量确认阈值 ──────────────────────────────────────
    #  修复 P0-1: BC/SC 需要 true 巨量确认（量比 2.5+），避免低量比突破被误判
    VOLUME_CONFIRMATION: Annotated[Dict[str, float], Field(description="成交量确认阈值")] = {
        'strong': 2.5,      # BC/SC: 真正的买入/抛售高潮需要 2.5x+ 巨量
        'moderate': 1.5,    # SOS/SOW/LPS: 1.5x 量能确认
        'weak': 0.8         # 一般信号: 0.8x 基准
    }

    # ── 收盘位置确认 ──────────────────────────────────────
    CLOSE_POSITION_CONFIRMATION: Annotated[float, Field(description="收盘位置确认")] = 0.7
    RECOVERY_DAYS: Annotated[int, Field(description="恢复天数")] = 3

    # ── 新威科夫操盘法（孟洪涛）JOC 参数 ──────────────────────
    # JOC (Jump Across the Creek / 跃过小溪)
    JOC_CREEK_QUANTILE: Annotated[float, Field(description="近期区间高点分位数（小溪阻力）")] = 0.85
    JOC_BODY_RATIO: Annotated[float, Field(description="突破日实体占波幅最小比例")] = 0.55
    JOC_UPPER_SHADOW_RATIO: Annotated[float, Field(description="上影线最大占波幅比例")] = 0.25
    JOC_VOLUME_RATIO: Annotated[float, Field(description="突破日最小量比（相对20日均量）")] = 1.5
    JOC_MIN_BREAKOUT_PCT: Annotated[float, Field(description="突破日最小涨幅百分比；不同市场可调，避免硬编码5%")] = 3.0
    JOC_EXCELLENT_BREAKOUT_PCT: Annotated[float, Field(description="优秀突破阈值，用于置信度评分")] = 5.0
    JOC_CLOSE_POSITION: Annotated[float, Field(description="突破日收盘位置下限（0=最低，1=最高）")] = 0.75
    JOC_TEST_BAND: Annotated[float, Field(description="回测允许偏离小溪位的比例 (±2%)")] = 0.02
    JOC_TEST_VOL_RATIO: Annotated[float, Field(description="回测日量能萎缩阈值（< 均量85%）")] = 0.85
    JOC_TEST_MIN_SCORE: Annotated[float, Field(description="回测最低质量分，低于此分不计入 test_detected")] = 60.0
    JOC_EXCELLENT_VOLUME_RATIO: Annotated[float, Field(description="优秀量能阈值，用于置信度评分")] = 2.5
    JOC_EXCELLENT_CLOSE_POSITION: Annotated[float, Field(description="优秀收盘位置阈值，用于置信度评分")] = 0.9
    JOC_GOOD_CLOSE_POSITION: Annotated[float, Field(description="良好收盘位置阈值，用于置信度评分")] = 0.8
    JOC_GOOD_VOLUME_RATIO: Annotated[float, Field(description="良好量能阈值，用于置信度评分")] = 2.0

    # ── AR (Automatic Rally/Reaction) 立即反弹参数 ────────────
    AR_MIN_REBOUND_PCT: Annotated[float, Field(description="AR 立即反弹/回落判定最低百分比阈值")] = 3.0

    # ── FTI (Fall Through the Ice / 跌破冰层) 参数 ────────────
    FTI_ICE_QUANTILE: Annotated[float, Field(description="近期区间低点分位数（冰层支撑）")] = 0.15
    FTI_BODY_RATIO: Annotated[float, Field(description="跌破日实体占波幅最小比例")] = 0.55
    FTI_LOWER_SHADOW_RATIO: Annotated[float, Field(description="下影线最大占波幅比例")] = 0.25
    FTI_VOLUME_RATIO: Annotated[float, Field(description="跌破日最小量比")] = 1.5
    FTI_TEST_BAND: Annotated[float, Field(description="回测允许偏离冰层位的比例 (±2%)")] = 0.02
    FTI_TEST_VOL_RATIO: Annotated[float, Field(description="回测日量能萎缩阈值")] = 0.85

    # ── VSA (Volume Spread Analysis) 参数 ─────────────────────
    VSA_NO_SUPPLY_BODY_RATIO: Annotated[float, Field(description="No Supply: 实体最大占波幅比")] = 0.45
    VSA_NO_SUPPLY_VOL_RATIO: Annotated[float, Field(description="No Supply: 量能上限（<均量60%，书：极度萎缩<50%）")] = 0.60
    VSA_NO_SUPPLY_CLOSE_POS: Annotated[float, Field(description="No Supply: 收盘最低位置（书：中高位）")] = 0.50
    VSA_NO_DEMAND_BODY_RATIO: Annotated[float, Field(description="No Demand: 实体最大占波幅比")] = 0.45
    VSA_NO_DEMAND_VOL_RATIO: Annotated[float, Field(description="No Demand: 量能上限（<均量60%）")] = 0.60
    VSA_NO_DEMAND_CLOSE_POS: Annotated[float, Field(description="No Demand: 收盘最高位置（书：中低位）")] = 0.75
    VSA_STOPPING_VOL_RATIO: Annotated[float, Field(description="Stopping Volume: 量能下限")] = 1.50
    VSA_STOPPING_BODY_RATIO: Annotated[float, Field(description="Stopping Volume: 实体最大占波幅比")] = 0.40
    VSA_STOPPING_CLOSE_POS: Annotated[float, Field(description="Stopping Volume: 收盘最低位置")] = 0.45
    VSA_BAG_HOLDING_VOL_RATIO: Annotated[float, Field(description="Bag Holding成交量倍数")] = 3.0
    VSA_SHAKEOUT_DEPTH: Annotated[float, Field(description="Shakeout深度阈值")] = 0.05

    # ── 涨跌停判断 ──────────────────────────────────────
    LIMIT_UP_THRESHOLD: Annotated[float, Field(description="涨停阈值")] = 0.095
    LIMIT_DOWN_THRESHOLD: Annotated[float, Field(description="跌停阈值")] = -0.095

    # ── 高级评分权重 ──────────────────────────────────────
    QUALITY_WEIGHTS: Annotated[Dict[str, float], Field(description="信号质量分项权重")] = {
        'volume_ratio': 0.3,
        'price_pct': 0.3,
        'confidence': 0.2,
        'confirmation': 0.2
    }
    TIME_DECAY_HALF_LIFE: Annotated[int, Field(description="信号强度随时间衰减的半衰期（天）")] = 20
    CONFLICT_PENALTY: Annotated[float, Field(description="多空冲突时的扣分 (v2.1校准)")] = 15.0

    # ── 孟洪涛增强器阈值 (MENG_ENHANCER) ────────────────────
    MENG_SPRING_BREAKDOWN_MIN: Annotated[float, Field(description="Spring跌破最小百分比")] = 1.0
    MENG_SPRING_BREAKDOWN_MAX: Annotated[float, Field(description="Spring跌破最大百分比")] = 3.0
    MENG_SPRING_RECOVERY_CLOSE_POS: Annotated[float, Field(description="Spring收回日最小收盘位置")] = 0.7
    MENG_SPRING_VOL_RATIO: Annotated[float, Field(description="Spring收回日量比要求")] = 1.0

    MENG_VSA_BODY_RATIO: Annotated[float, Field(description="VSA(无供应/无需求)实体最大占比")] = 0.3
    MENG_VSA_VOL_RATIO: Annotated[float, Field(description="VSA(无供应/无需求)成交量上限")] = 0.6
    MENG_VSA_CLOSE_POS: Annotated[float, Field(description="VSA(无供应)最小收盘位置")] = 0.5

    MENG_STOPPING_VOL_RATIO: Annotated[float, Field(description="Stopping Volume最小量比")] = 1.5
    MENG_STOPPING_BODY_RATIO: Annotated[float, Field(description="Stopping Volume实体最大占比")] = 0.3
    MENG_STOPPING_SHADOW_RATIO: Annotated[float, Field(description="Stopping Volume下影线最小占比")] = 0.3

    # ── 交易成本与滑点 ──────────────────────────────────
    COMMISSION_RATE: Annotated[float, Field(description="佣金率 (万三)")] = 0.0003
    SLIPPAGE_RATE: Annotated[float, Field(description="双边滑点 (10 BP)")] = 0.001
    IMPACT_COST_RATE: Annotated[float, Field(description="冲击成本 (5 BP)")] = 0.0005

    # ── 评分与仓位配置 ──────────────────────────────────────
    SCORING: Annotated[ScoringConfig, Field(description="评分表显式配置")] = ScoringConfig()
    POSITION_SIZING: Annotated[PositionSizingConfig, Field(description="仓位管理详细配置")] = PositionSizingConfig()

    # ── WIE 3.0 状态机阈值 (P2.3) ──────────────────────────
    STATE_ENTROPY_DEGRADED_THRESHOLD: Annotated[float, Field(description="状态熵降级阈值 (6状态最大熵 ln(6)≈1.79，超过此值表示高度不确定)")] = 1.55
    CLIMAX_SQUAT_VOL_MULTIPLIER: Annotated[float, Field(description="蹲坐柱量能倍数")] = 2.0
    CLIMAX_SQUAT_SPREAD_RATIO: Annotated[float, Field(description="蹲坐柱价差比例上限")] = 0.8
    CLIMAX_SQUAT_CONFIDENCE_BONUS: Annotated[float, Field(description="蹲坐柱联动置信度加成")] = 1.15
    EVR_BREAKDOWN_CLV_THRESHOLD: Annotated[float, Field(description="溃败CLV阈值")] = -0.6
    EVR_BREAKDOWN_EFF_THRESHOLD: Annotated[float, Field(description="溃败效率阈值")] = 0.5

    def get_volatility_threshold(self, threshold_type: str, volatility_class: str) -> float:
        """获取波动率阈值"""
        thresholds = self.VOLATILITY_THRESHOLDS.get(threshold_type, {})
        return thresholds.get(volatility_class, 0.035)

    def get_dynamic_volume_threshold(self, atr_pct: float, base_threshold: float = 1.5) -> float:
        """基于ATR百分比动态计算成交量阈值"""
        if atr_pct <= 0 or base_threshold <= 0:
            raise ValueError(f'ATR百分比和基础阈值必须为正数 (atr_pct={atr_pct}, base_threshold={base_threshold})')
        if atr_pct > 0.5:
            raise ValueError(f'ATR百分比异常高 (atr_pct={atr_pct})，请检查数据')

        if self.market_type == "CRYPTO":
            if atr_pct < 0.03:
                result = base_threshold
            elif atr_pct < 0.06:
                result = base_threshold * 1.2
            elif atr_pct < 0.10:
                result = base_threshold * 1.5
            else:
                result = base_threshold * 2.0
            return max(0.5, min(result, 5.0))

        if atr_pct < 0.015:
            result = base_threshold * 0.8
        elif atr_pct < 0.03:
            result = base_threshold
        elif atr_pct < 0.05:
            result = base_threshold * 1.2
        else:
            result = base_threshold * 1.5
        return max(0.5, min(result, 5.0))

    def get_dynamic_price_threshold(self, atr_pct: float, base_threshold: float = 0.03) -> float:
        """基于ATR百分比动态计算价格变化阈值"""
        if atr_pct <= 0 or base_threshold <= 0:
            raise ValueError(f'ATR百分比和基础阈值必须为正数 (atr_pct={atr_pct}, base_threshold={base_threshold})')
        if atr_pct > 0.5:
            raise ValueError(f'ATR百分比异常高 (atr_pct={atr_pct})，请检查数据')

        if self.market_type == "CRYPTO":
            if atr_pct < 0.03:
                result = max(atr_pct * 1.2, base_threshold * 1.2)
            elif atr_pct < 0.06:
                result = max(atr_pct * 1.5, base_threshold * 1.5)
            elif atr_pct < 0.10:
                result = max(atr_pct * 2.0, base_threshold * 2.0)
            else:
                result = max(atr_pct * 2.5, base_threshold * 3.0)
            return max(0.01, min(result, 0.3)) # 上限提高到30%

        if atr_pct < 0.015:
            result = max(atr_pct * 1.0, base_threshold * 0.8)
        elif atr_pct < 0.03:
            result = max(atr_pct * 1.5, base_threshold)
        elif atr_pct < 0.05:
            result = max(atr_pct * 2.0, base_threshold * 1.2)
        else:
            result = max(atr_pct * 2.5, base_threshold * 1.5)
        return max(0.005, min(result, 0.2))

    def classify_volatility(self, atr_pct: float) -> str:
        """根据ATR百分比分类波动率

        Args:
            atr_pct: ATR占价格的百分比数值，如1.5代表1.5%。
                     注意：请传入百分比数值（如1.5），而非小数（如0.015）。
                     两者量纲一致性由防守性校验保障。

        Returns:
            波动率分级：'low' | 'medium' | 'high' | 'extreme'

        Raises:
            ValueError: atr_pct为非正数或检测到潜在量纲混淆（传入了小数而非百分比）
        """
        if atr_pct <= 0:
            raise ValueError(f"ATR百分比必须为正数 (atr_pct={atr_pct})")
        if atr_pct < 0.2:
            raise ValueError(
                f"检测到潜在的参数量纲混淆错误。"
                f"请传入百分比数值（如 1.5 代表 1.5%），而非小数 (atr_pct={atr_pct})"
            )

        boundaries = self.CRYPTO_VOL_BOUNDARIES if self.market_type == "CRYPTO" else self.DEFAULT_VOL_BOUNDARIES

        if atr_pct < boundaries['low']:
            return 'low'
        elif atr_pct < boundaries['medium']:
            return 'medium'
        elif atr_pct < boundaries['high']:
            return 'high'
        else:
            return 'extreme'

class WyckoffConfig(BaseModel):
    """威科夫分析配置（带验证）"""
    confidence_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.85
    min_data_length: Annotated[int, Field(ge=20, le=1000)] = 60
    atr_period: Annotated[int, Field(ge=5, le=50)] = 14
    atr_multiplier: Annotated[float, Field(ge=0.5, le=5.0)] = 1.5
    volume_ma_period: Annotated[int, Field(ge=5, le=100)] = 20

    #  v1.3新增：动态阈值系统
    enable_adaptive_thresholds: Annotated[bool, Field(description="启用动态阈值自适应系统")] = True
    adaptive_thresholds_atr_period: Annotated[int, Field(ge=5, le=50, description="动态阈值ATR计算周期")] = 14

    # 贝叶斯自适应阈值参数
    prior_breakout_mu: Annotated[float, Field(ge=1.0, le=5.0, description="突破量比先验均值")] = 1.5
    prior_shrink_mu: Annotated[float, Field(ge=0.1, le=1.0, description="缩量量比先验均值")] = 0.6
    prior_sigma: Annotated[float, Field(ge=0.1, le=2.0, description="量比先验标准差")] = 0.5
    amplitude_breakout_percentile: Annotated[float, Field(ge=50.0, le=99.0, description="贝叶斯推断：突破日振幅截取分位数")] = 85.0
    amplitude_shrink_percentile: Annotated[float, Field(ge=1.0, le=50.0, description="贝叶斯推断：缩量日振幅截取分位数")] = 15.0

    # Spring检测参数
    spring_lookback: Annotated[int, Field(ge=30, le=252)] = 120
    spring_max_recovery_days: Annotated[int, Field(ge=1, le=10)] = 3
    spring_range_threshold: Annotated[float, Field(ge=0.1, le=0.5)] = 0.30

    climax_range_multiplier: Annotated[float, Field(ge=1.0, le=5.0)] = 1.5

    # 突破搜索窗口 (Spring/Upthrust 搜索最后 M 根 K线)
    breakout_search_window: Annotated[int, Field(ge=1, le=20)] = 5

    # ── 阈值与成本配置 ──────────────────────────────────────
    thresholds: Annotated[WyckoffThresholds, Field(description="威科夫分析阈值集中配置")] = WyckoffThresholds()

    # ── 错误处理策略 (P0 重构) ─────────────────────────────
    silent_fail: Annotated[bool, Field(description="静默失败模式。True: 捕获异常并返回空结果 (适用于批量扫描); False: 向上抛出异常，确保错误不被掩盖 (适用于单股深度分析)")] = False
    max_retries: Annotated[int, Field(description="数据获取失败时的最大重试次数")] = 3

    @field_validator('min_data_length')
    @classmethod
    def validate_data_length(cls, v):
        if v < 20:
            raise ValueError('数据长度至少20天')
        return v

    @field_validator('atr_period')
    @classmethod
    def validate_atr_period(cls, v):
        if v < 5 or v > 50:
            raise ValueError('ATR周期必须在5-50之间')
        return v

    @field_validator('spring_lookback')
    @classmethod
    def validate_spring_lookback(cls, v):
        if v < 30:
            raise ValueError('Spring回溯窗口至少30天')
        return v

    @field_validator('spring_range_threshold')
    @classmethod
    def validate_spring_range(cls, v):
        if not 0.05 <= v <= 0.5:
            raise ValueError('Spring范围阈值必须在0.05-0.5之间')
        return v

    @model_validator(mode='after')
    def validate_config_dependencies(self):
        if self.atr_period >= self.min_data_length:
            raise ValueError(f'ATR周期 ({self.atr_period}) 必须小于最小数据长度 ({self.min_data_length})')
        if self.spring_lookback < self.min_data_length / 2:
            raise ValueError(f'Spring回溯窗口 ({self.spring_lookback}) 应该至少是最小数据长度的一半 ({self.min_data_length / 2:.0f})')
        if self.volume_ma_period >= self.min_data_length:
            raise ValueError(f'成交量MA周期 ({self.volume_ma_period}) 必须小于最小数据长度 ({self.min_data_length})')
        return self

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        extra='allow'
    )
