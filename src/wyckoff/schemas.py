"""
威科夫分析系统数据模型
定义所有JSON接口的强类型模型
"""
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Any, Optional
from .core.enums import MarketEnvironment, WyckoffPhase
from .core.enums import ErrorCode


# ============================================================
# 基础数据模型
# ============================================================

class DerivedValueModel(BaseModel):
    """带推导逻辑的数值模型 (P1 #3)"""
    value: float = Field(description="数值")
    derivation: Optional[str] = Field(default=None, description="推导逻辑/来源")
    note: Optional[str] = Field(default=None, description="备注说明")

    @model_validator(mode='before')
    @classmethod
    def wrap_float(cls, data: Any) -> Any:
        if isinstance(data, (int, float)):
            return {"value": float(data), "derivation": "legacy_data", "note": "兼容性自动转换"}
        return data

class BasicDataModel(BaseModel):
    """基础数据"""
    current_price: float = Field(description="当前价格")
    volume: int = Field(description="成交量")
    volume_ratio: float = Field(description="量比")


class MultiTimeframeModel(BaseModel):
    """多时间框架分析"""
    weekly_trend: str = Field(description="周线趋势")
    monthly_trend: str = Field(description="月线趋势")
    agreement: str = Field(description="多时间框架一致性")


# ============================================================
# 事件检测模型
# ============================================================

class WyckoffEventModel(BaseModel):
    """威科夫事件基础模型"""
    detected: bool = Field(description="是否检测到")
    date: Optional[Any] = None
    price: Optional[float] = Field(default=None, description="事件价格")
    volume: Optional[float] = Field(default=None, description="事件成交量")
    volume_ratio: Optional[float] = Field(default=None, description="事件量比")
    confidence: float = Field(default=0.0, description="置信度 (0-1)")
    description: Optional[str] = Field(default=None, description="事件描述")
    # 新增字段：反弹/回落百分比（从Climax实体中位值计算）
    rebound_pct: Optional[float] = Field(default=None, description="反弹百分比（用于SC后的AR）")
    decline_pct: Optional[float] = Field(default=None, description="回落百分比（用于BC后的AR）")
    sc_benchmark: Optional[float] = Field(default=None, description="SC/BC实体中位值（计算基准）")

class BaseDetectionResult(BaseModel):
    """通用检测结果包装器 (P0 #1)"""
    detected: bool = Field(description="是否检测到")
    confidence: float = Field(default=0.0, description="置信度")
    description: Optional[str] = Field(default=None, description="文字描述")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据/原始数据")
    error_code: Optional[ErrorCode] = Field(default=None, description="错误代码")


class TradingRangeModel(BaseModel):
    """交易区间模型"""
    is_consolidation: bool = Field(description="是否为整理区间")
    is_broken: Optional[bool] = Field(default=False, description="区间是否已被突破失效")
    breakout_direction: Optional[str] = Field(default=None, description="突破方向")
    high: float = Field(description="区间高点")
    low: float = Field(description="区间低点")
    range_pct: float = Field(description="区间幅度百分比")
    duration_days: int = Field(description="持续天数")
    consolidation_duration_days: int = Field(default=60, description="动态估算的积累/分布持续天数")
    volume_trend: str = Field(default="neutral", description="成交量趋势")
    position: float = Field(description="当前价格在区间中的位置")
    current_price: float = Field(description="当前价格")


class ClimaxModel(BaseModel):
    """高潮事件"""
    detected: bool = Field(description="是否检测到")
    error: Optional[str] = Field(default=None, description="错误信息")
    type: Optional[str] = Field(default=None, description="高潮类型")
    date: Optional[Any] = None
    price: Optional[float] = Field(default=None, description="价格")
    volume: Optional[float] = Field(default=None, description="成交量")
    volume_ratio: Optional[float] = Field(default=None, description="量比")
    is_confirmed: bool = Field(default=False, description="是否已通过AR确认")
    confirmation_date: Optional[Any] = Field(default=None, description="确认日期")


class SpringSignalModel(BaseModel):
    """Spring信号详情"""
    date: Optional[Any] = None
    breakdown_date: Any = Field(description="跌破日期")
    breakdown_price: Any = Field(description="跌破价格")
    support_level: Any = Field(description="支撑位")
    recovery_price: Any = Field(description="收回价格")
    recovery_days: int = Field(description="收回天数")
    volume_ratio: float = Field(description="量比")
    shadow_ratio: Optional[float] = Field(default=None, description="下影线与实体比例")
    total_score: Optional[float] = Field(default=None, description="综合评分(0-100)")
    strength: Optional[str] = Field(default=None, description="信号强度: strong/normal/weak")
    spring_type: Optional[Any] = Field(default=None, description="Spring类型")
    lifecycle_status: str = Field(default="active", description="生命周期状态: active/confirmed/failed")
    st_confirmed: Optional[bool] = Field(default=None, description="二次测试是否确认")
    breakdown_volume: Optional[float] = Field(default=None, description="突破日成交量")


class SpringModel(BaseModel):
    """Spring事件"""
    detected: bool = Field(description="是否检测到")
    reason: Optional[str] = Field(default=None, description="未检测到的原因")
    signals: Optional[List[SpringSignalModel]] = Field(default=None, description="信号列表")
    latest_spring: Optional[SpringSignalModel] = Field(default=None, description="最新Spring")


class UpthrustSignalModel(BaseModel):
    """Upthrust信号详情"""
    date: Optional[Any] = None
    breakout_date: Any = Field(description="突破日期")
    breakout_price: Any = Field(description="突破价格")
    resistance_level: Any = Field(description="阻力位")
    rejection_price: Any = Field(description="回落价格")
    rejection_days: int = Field(description="回落天数")
    close_from_high: float = Field(description="收盘距高点比例")
    follow_through_quality: Optional[float] = Field(default=None, description="回落跟随质量")
    breakout_volume_ratio: Optional[float] = Field(default=None, description="突破量比")
    penetration_depth: Optional[float] = Field(default=None, description="向上刺穿深度(%)")
    upthrust_type: Optional[str] = Field(default=None, description="Upthrust类型(Type1/2/3)")
    needs_secondary_test: Optional[bool] = Field(default=None, description="是否需要ST")
    is_valid: Optional[bool] = Field(default=None, description="是否为有效信号")


class UpthrustModel(BaseModel):
    """Upthrust事件"""
    detected: bool = Field(description="是否检测到")
    reason: Optional[str] = Field(default=None, description="未检测到的原因")
    signals: Optional[List[UpthrustSignalModel]] = Field(default=None, description="信号列表")
    latest_upthrust: Optional[UpthrustSignalModel] = Field(default=None, description="最新Upthrust")


class SosSignalModel(BaseModel):
    """SOS信号详情"""
    date: Optional[Any] = None
    price: Any = Field(description="价格")
    volume_ratio: float = Field(description="量比")
    price_change: float = Field(description="涨幅")
    breakthrough_level: Any = Field(description="突破位")


class SosModel(BaseModel):
    """SOS事件"""
    detected: bool = Field(description="是否检测到")
    error: Optional[str] = Field(default=None, description="错误信息")
    signals: Optional[List[SosSignalModel]] = Field(default=None, description="信号列表")
    latest: Optional[SosSignalModel] = Field(default=None, description="最新SOS")
    breakout_type: Optional[str] = Field(default=None, description="突破类型: breakout_sos/range_high_sos/within_range_sos")
    interpretation: Optional[str] = Field(default=None, description="当前上下文下的信号解释")


class SowSignalModel(BaseModel):
    """SOW信号详情"""
    date: Optional[Any] = None
    price: Any = Field(description="价格")
    volume_ratio: float = Field(description="量比")
    price_change: float = Field(description="跌幅")
    breakdown_level: Any = Field(description="跌破位")


class SowModel(BaseModel):
    """SOW事件"""
    detected: bool = Field(description="是否检测到")
    error: Optional[str] = Field(default=None, description="错误信息")
    signals: Optional[List[SowSignalModel]] = Field(default=None, description="信号列表")
    latest: Optional[SowSignalModel] = Field(default=None, description="最新SOW")


class LpsSignalModel(BaseModel):
    """LPS信号详情"""
    date: Optional[Any] = None
    price: float = Field(description="价格")
    volume_ratio: float = Field(description="量比")
    support_level: float = Field(description="支撑位")
    signal_type: Optional[str] = Field(default=None, description="信号类型: lps/pullback/pullback_weak")
    note: Optional[str] = Field(default=None, description="阶段上下文说明")

class LpsModel(BaseModel):
    """LPS事件"""
    detected: bool = Field(description="是否检测到")
    error: Optional[str] = Field(default=None, description="错误信息")
    signals: Optional[List[LpsSignalModel]] = Field(default=None, description="信号列表")
    latest: Optional[LpsSignalModel] = Field(default=None, description="最新LPS")
    phase_context: Optional[Dict[str, Any]] = Field(default=None, description="检测时的阶段上下文")


class LpsySignalModel(BaseModel):
    """LPSY信号详情"""
    date: Optional[Any] = None
    price: float = Field(description="价格")
    volume_ratio: float = Field(description="量比")
    resistance_level: float = Field(description="阻力位")
    signal_type: Optional[str] = Field(default=None, description="信号类型: lpsy/weak_reaction")
    volume: Optional[float] = Field(default=None, description="实际成交量")

class LpsyModel(BaseModel):
    """LPSY事件"""
    detected: bool = Field(description="是否检测到")
    error: Optional[str] = Field(default=None, description="错误信息")
    signals: Optional[List[LpsySignalModel]] = Field(default=None, description="LPSY信号列表")
    weak_reactions: Optional[List[LpsySignalModel]] = Field(default=None, description="弱势反抽列表(未破支撑)")
    latest: Optional[LpsySignalModel] = Field(default=None, description="最新LPSY")
    support_level: Optional[float] = Field(default=None, description="TR支撑位(冰线)")
    support_broken: Optional[bool] = Field(default=None, description="支撑是否已被有效跌破")

class JocModel(BaseModel):
    """JOC (Jump Over Creek) 模型"""
    detected: bool = Field(description="是否检测到")
    date: Optional[Any] = None
    creek_level: float = Field(default=0.0, description="小溪位")
    breakout_pct: float = Field(default=0.0, description="突破幅度")
    test_detected: bool = Field(default=False, description="是否检测到回测")
    test_quality: Optional[str] = Field(default=None, description="回测质量: HIGH/MEDIUM/LOW")
    test_score: float = Field(default=0.0, description="回测质量评分(0-100)")
    confidence: float = Field(default=0.0, description="置信度")

class FtiModel(BaseModel):
    """FTI (Fall Through Ice) 模型"""
    detected: bool = Field(description="是否检测到")
    date: Optional[Any] = None
    ice_level: float = Field(default=0.0, description="冰层位")
    breakdown_pct: float = Field(default=0.0, description="跌破幅度")
    confidence: float = Field(default=0.0, description="置信度")


class SequenceValidationModel(BaseModel):
    """事件序列验证结果"""
    spring: Dict[str, Any] = Field(default_factory=dict, description="Spring前置结构验证")
    lps: Dict[str, Any] = Field(default_factory=dict, description="LPS与Spring/SOS关系验证")
    sos: Dict[str, Any] = Field(default_factory=dict, description="SOS前置验证")
    joc: Dict[str, Any] = Field(default_factory=dict, description="JOC回测验证")
    sequence_score: Dict[str, Any] = Field(default_factory=dict, description="序列完整性评分")
    conflicts: List[str] = Field(default_factory=list, description="检测到的逻辑矛盾")


class ArbitrationSignal(BaseModel):
    """参与仲裁的信号"""
    signal_type: str = Field(description="信号类型: spring/lpsy/sos/sow等")
    date: Optional[Any] = Field(description="信号日期")
    direction: str = Field(description="信号方向: bullish/bearish")
    confidence: float = Field(description="信号置信度")
    strength: Optional[float] = Field(default=None, description="信号强度")
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="原始信号数据")


class ArbitrationResult(BaseModel):
    """事件仲裁结果"""
    has_conflict: bool = Field(description="是否存在冲突信号")
    conflicting_signals: List[ArbitrationSignal] = Field(default_factory=list, description="冲突的信号列表")
    dominant_signal: Optional[ArbitrationSignal] = Field(default=None, description="主导信号")
    rejected_signals: List[ArbitrationSignal] = Field(default_factory=list, description="被拒绝的信号")
    arbitration_reason: str = Field(description="仲裁理由")
    suggested_phase: Optional[str] = Field(default=None, description="建议的阶段")
    phase_adjustment: Optional[str] = Field(default=None, description="阶段调整说明")
    confidence_adjustment: float = Field(default=1.0, description="置信度调整系数")


class DualEventModel(BaseModel):
    """二选一结构包装器"""
    type_: str = Field(alias="_type", description="事件类型")
    data: Any = Field(description="底层事件模型数据")

class BoringZoneModel(BaseModel):
    """枯燥区检测结果"""
    detected: bool = Field(default=False)
    score: int = Field(default=0)
    vol_contraction: float = Field(default=0.0)
    atr_contraction: float = Field(default=0.0)
    duration: int = Field(default=0)
    high_alert: bool = Field(default=False)
    is_eve_of_breakout: bool = Field(default=False)
    signal_status: str = Field(default="NONE")
    reason: Optional[str] = Field(default=None)

class BreakoutAnalysisModel(BaseModel):
    """突破质量分析结果"""
    is_breakout: bool = Field(default=False)
    direction: str = Field(default="none")
    breakout_date: Optional[Any] = Field(default=None)
    breakout_price: Optional[float] = Field(default=None)
    breakout_volume: Optional[float] = Field(default=None)
    quality: Optional[str] = Field(default=None)
    quality_score: Optional[int] = Field(default=None)
    is_upthrust: Optional[bool] = Field(default=None)
    volume_analysis: Optional[Dict[str, Any]] = Field(default=None)
    pullback_analysis: Optional[Dict[str, Any]] = Field(default=None)
    post_breakout_analysis: Optional[Dict[str, Any]] = Field(default=None)
    joc_test_status: Optional[str] = Field(default=None)
    conclusion: Optional[str] = Field(default=None)
    reason: Optional[str] = Field(default=None)

class EventsModel(BaseModel):
    """所有事件 — 所有子事件字段均为 Optional，仅 trading_range 必填"""
    trading_range: TradingRangeModel = Field(description="交易区间")
    climax: Optional[ClimaxModel] = Field(default=None, description="高潮事件")
    automatic_reaction: Optional[WyckoffEventModel] = Field(default=None, description="自动反应")
    secondary_test: Optional[WyckoffEventModel] = Field(default=None, description="二次测试")
    spring: Optional[SpringModel] = Field(default=None, description="Spring事件")
    upthrust: Optional[UpthrustModel] = Field(default=None, description="Upthrust事件")
    sos: Optional[SosModel] = Field(default=None, description="SOS事件")
    sow: Optional[SowModel] = Field(default=None, description="SOW事件")
    lps: Optional[LpsModel] = Field(default=None, description="LPS事件")
    lpsy: Optional[LpsyModel] = Field(default=None, description="LPSY事件")
    joc: Optional[JocModel] = Field(default=None, description="JOC事件")
    fti: Optional[FtiModel] = Field(default=None, description="FTI事件")
    arbitration_result: Optional[ArbitrationResult] = Field(default=None, description="事件仲裁结果")

    # === 新增补充字段 ===
    lps_list: List[Dict[str, Any]] = Field(default_factory=list, description="LPS序列列表")
    ut_list: List[Dict[str, Any]] = Field(default_factory=list, description="UT序列列表")
    spring_upthrust: Optional[DualEventModel] = Field(default=None, description="二选一结果")
    sos_sow: Optional[DualEventModel] = Field(default=None, description="二选一结果")
    lps_lpsy: Optional[Dict[str, Any]] = Field(default=None, description="LPS/LPSY字典组合")
    boring_zone: Optional[BoringZoneModel] = Field(default=None, description="枯燥区检测")
    phase_revision_log: List[str] = Field(default_factory=list, description="阶段修订日志")
    breakout_analysis: Optional[BreakoutAnalysisModel] = Field(default=None, description="突破分析")
    preliminary_support: Optional[WyckoffEventModel] = Field(default=None, description="PS事件")
    preliminary_supply: Optional[WyckoffEventModel] = Field(default=None, description="PSY事件")
    utad: Optional[WyckoffEventModel] = Field(default=None, description="UTAD事件")
    choch: Optional[WyckoffEventModel] = Field(default=None, description="CHoCH事件")
    sequence_validation: Optional[Any] = Field(default=None, description="事件序列验证")


# ============================================================
# 信号质量模型
# ============================================================

class SignalQualityModel(BaseModel):
    """信号质量评分"""
    score: int = Field(description="得分")
    max_score: int = Field(default=10, description="最高分")
    confidence: str = Field(description="信心级别")
    reasons: List[str] = Field(default_factory=list, description="评分原因")

    def __getitem__(self, item):
        return getattr(self, item)


# ============================================================
# 交易计划模型
# ============================================================

class StopLossModel(BaseModel):
    """止损设置"""
    conservative: Any = Field(description="保守止损")
    aggressive: Any = Field(description="激进止损")
    atr_dynamic_stop: Optional[Any] = Field(default=None, description="ATR动态止损")


class TargetsModel(BaseModel):
    """目标位"""
    target_1: Any = Field(description="第一目标")
    target_2: Any = Field(description="第二目标")


class PositionSizingModel(BaseModel):
    """仓位管理"""
    conservative: str = Field(description="保守仓位")
    moderate: str = Field(description="稳健仓位")
    aggressive: str = Field(description="激进仓位")


class TradingPlanModel(BaseModel):
    """交易计划"""
    direction: str = Field(description="操作方向")
    entry_zone: str = Field(description="入场区间")
    stop_loss: StopLossModel = Field(description="止损设置")
    targets: TargetsModel = Field(description="目标位")
    position_sizing: PositionSizingModel = Field(description="仓位管理")
    holding_period: str = Field(description="持有周期")


# ============================================================
# 风险建议模型
# ============================================================

class RiskAdviceItem(BaseModel):
    """风险建议项"""
    action: Optional[str] = Field(default=None, description="建议操作")
    reason: Optional[str] = Field(default=None, description="原因")
    position: Optional[str] = Field(default=None, description="仓位")
    stop_loss: Optional[str] = Field(default=None, description="止损")
    entry_condition: Optional[str] = Field(default=None, description="入场条件")

    def __getitem__(self, item):
        return getattr(self, item)


class RiskAdviceModel(BaseModel):
    """风险分层建议"""
    conservative: RiskAdviceItem = Field(description="保守型")
    moderate: RiskAdviceItem = Field(description="稳健型")
    aggressive: RiskAdviceItem = Field(description="激进型")

    def __getitem__(self, item):
        return getattr(self, item)


# ============================================================
# 市场环境模型
# ============================================================

class MarketContextModel(BaseModel):
    """市场环境"""
    index_symbol: Optional[str] = Field(default=None, description="指数代码")
    phase: Optional[str] = Field(default=None, description="市场阶段")
    environment: Optional[MarketEnvironment] = Field(default=MarketEnvironment.UNKNOWN, description="市场环境")
    ma_spread_pct: Optional[float] = Field(default=None, description="均线偏离度")


class GlobalSentimentModel(BaseModel):
    """全球市场情绪"""
    market_sentiment: str = Field(description="市场情绪")
    vix_level: Optional[float] = Field(default=None, description="VIX水平")
    implication: str = Field(description="含义")
    benchmark_used: Optional[str] = Field(default=None, description="基准")


# ============================================================
# 威科夫法则模型
# ============================================================

class SupplyDemandLawModel(BaseModel):
    """供求法则"""
    current_phase: Any = Field(description="当前阶段")
    trading_range_status: str = Field(description="交易区间状态")
    volume_analysis: Dict[str, Any] = Field(description="成交量分析")


class EffortVsResultModel(BaseModel):
    """努力与结果法则"""
    overall_assessment: str = Field(description="总体评估")
    wyckoff_guidance: str = Field(description="威科夫指导")
    timeframe_analysis: Dict[str, Any] = Field(description="时间框架分析")


class CauseEffectModel(BaseModel):
    """因果法则"""
    basic_analysis: Optional[Dict[str, Any]] = Field(default=None, description="基础分析")
    enhanced_analysis: Optional[Dict[str, Any]] = Field(default=None, description="增强分析")


class WyckoffLawsModel(BaseModel):
    """威科夫三大法则"""
    supply_demand_law: SupplyDemandLawModel = Field(description="供求法则")
    effort_vs_result_law: EffortVsResultModel = Field(description="努力与结果法则")
    cause_effect_law: CauseEffectModel = Field(description="因果法则")


# ============================================================
# 相对强度模型
# ============================================================

class RelativeStrengthModel(BaseModel):
    """相对强度"""
    benchmark_used: Optional[str] = Field(default=None, description="基准")
    rs_value: Optional[float] = Field(default=None, description="RS值")
    rs_ma20: Optional[float] = Field(default=None, description="20日RS均线")
    rs_ma50: Optional[float] = Field(default=None, description="50日RS均线")
    rs_trend: Optional[str] = Field(default=None, description="RS趋势")
    rs_change_20d: Optional[float] = Field(default=None, description="20日RS变化")


# ============================================================
# 序列评分模型
# ============================================================

class SequenceScoreModel(BaseModel):
    """序列评分"""
    completeness: float = Field(description="完整度")
    score: Optional[float] = Field(default=None, description="得分")
    adjustment_factor: Optional[float] = Field(default=None, description="调整因子")
    rating: str = Field(description="评级")
    missing_events: List[str] = Field(default_factory=list, description="缺失事件")


# ============================================================
# 背离检测模型
# ============================================================

class DivergenceModel(BaseModel):
    """背离检测"""
    detected: bool = Field(description="是否检测到")
    type: Optional[str] = Field(default=None, description="背离类型")


# ============================================================
# 历史表现模型
# ============================================================

class PerformanceItem(BaseModel):
    """历史表现项 (P0 #1)"""
    total_occurrences: int = Field(description="总出现次数")
    success_rate: str = Field(description="成功率")
    avg_return: str = Field(description="平均收益")
    pl_ratio: float = Field(default=0.0, description="盈亏比")
    max_drawdown: str = Field(default="0.0%", description="最大回撤")
    confidence_grade: str = Field(default="C", description="信心等级 (A/B/C)")
    note: Optional[str] = Field(default=None, description="备注")


# ============================================================
# 因果分析模型
# ============================================================

class CauseEffectAnalysisModel(BaseModel):
    """因果分析结果"""
    error: Optional[str] = Field(default=None, description="错误信息")
    basic_analysis: Optional[Dict[str, Any]] = Field(default=None, description="基础分析")
    cause_size: Optional[float] = Field(default=None, description="原因大小")
    breakout_point: Optional[float] = Field(default=None, description="突破点")
    targets: Optional[Any] = Field(default=None, description="目标位")
    current_position: Optional[float] = Field(default=None, description="当前位置")


# ============================================================
# 主报告模型
# ============================================================

class ReportModel(BaseModel):
    """威科夫分析报告"""
    symbol: str = Field(description="股票代码")
    date: str = Field(description="分析日期")
    phase: str = Field(description="当前阶段")
    phase_confidence: float = Field(description="阶段置信度")
    sequence_score: SequenceScoreModel = Field(description="序列评分")
    divergence: DivergenceModel = Field(description="背离检测")
    multi_timeframe: MultiTimeframeModel = Field(description="多时间框架")
    relative_strength: RelativeStrengthModel = Field(description="相对强度")
    basic_data: BasicDataModel = Field(description="基础数据")
    events: EventsModel = Field(description="事件检测")
    sequence_validation: SequenceValidationModel = Field(
        default_factory=SequenceValidationModel,
        description="事件序列验证"
    )
    cause_effect: CauseEffectAnalysisModel = Field(description="因果分析")
    market_context: MarketContextModel = Field(description="市场环境")
    global_sentiment: GlobalSentimentModel = Field(description="全球情绪")
    signal_quality: SignalQualityModel = Field(description="信号质量")
    trading_plan: TradingPlanModel = Field(description="交易计划")
    wyckoff_laws: WyckoffLawsModel = Field(description="威科夫法则")
    terminology_guide: Dict[str, Any] = Field(default_factory=dict, description="术语指南")
    risk_specific_advice: RiskAdviceModel = Field(description="风险建议")
    interactive_qa: List[str] = Field(default_factory=list, description="交互问答")
    performance_tracking: Dict[str, Any] = Field(default_factory=dict, description="历史表现")


# ============================================================
# 错误响应模型 (Phase 2A 兼容性)
# ============================================================

class ErrorResponseModel(BaseModel):
    """标准化错误响应 (保持向后兼容)"""
    error_code: str = Field(description="标准化错误码")
    error: str = Field(description="错误描述 (旧字段兼容)")
    type: str = Field(description="错误类型 (旧字段兼容)")
    retriable: bool = Field(default=False, description="是否可重试")
    trace_id: Optional[str] = Field(default=None, description="追踪ID")
    details: Optional[Dict[str, Any]] = Field(default=None, description="详细信息")
