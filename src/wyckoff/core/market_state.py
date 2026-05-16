from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

class RegimeState(Enum):
    """
    威科夫 MVP 六大底层离散状态 (WIE 3.0 MVP)
    """
    S0_PANIC_LIQUIDATION = "S0: Panic Liquidation (恐慌出清)"
    S1_ABSORPTION = "S1: Absorption (主力高密持续吸收)"
    S2_NEUTRAL_COMPRESSION = "S2: Neutral Compression (中性换手/时间磨底)"
    S3_DEMAND_EMERGENCE = "S3: Demand Emergence (需求萌芽/起跳突破)"
    S4_MARKUP = "S4: Markup (主升拉升展开)"
    S5_DISTRIBUTION = "S5: Distribution (高位派发)"

@dataclass
class MarketState:
    """
    威科夫事件驱动标准状态容器 (MarketState Container) - WIE 3.0 MVP
    """
    timestamp: str
    close: float
    regime: str
    
    # 核心物理指标层
    aps: float = 0.0              # 筹码吸收分
    cds: int = 0                  # 收敛时间记忆
    lcs: float = 0.0              # 死票参与甄别分
    vpoc_price: float = 0.0       # 后台筹码峰价位
    expansion_eff: float = 0.0    # 消除奇点后的推动效率
    clv: float = 0.0              # 日内吃单效率
    
    # 相对资本流动向
    liquidity_retention: float = 1.0
    hidden_strength: bool = False
    hidden_weakness: bool = False
    
    # 瞬态 Flag (如 Spring / Trap)
    event_flags: List[str] = field(default_factory=list)
    
    # 贝叶斯概率层与状态熵
    state_probs: Dict[str, float] = field(default_factory=dict)
    transition_paths: Dict[str, float] = field(default_factory=dict) # 新增: 下一步高概率演化路径
    state_entropy: float = 0.0
    is_confidence_degraded: bool = False  # 是否触发置信度降级自保保护令
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'close': self.close,
            'regime': self.regime,
            'aps': round(self.aps, 4),
            'cds': self.cds,
            'lcs': round(self.lcs, 4),
            'vpoc_price': round(self.vpoc_price, 2),
            'expansion_eff': round(self.expansion_eff, 4),
            'clv': round(self.clv, 4),
            'liquidity_retention': round(self.liquidity_retention, 4),
            'hidden_strength': self.hidden_strength,
            'hidden_weakness': self.hidden_weakness,
            'event_flags': self.event_flags,
            'state_probs': {k: round(v, 4) for k, v in self.state_probs.items()},
            'transition_paths': {k: round(v, 4) for k, v in self.transition_paths.items()},
            'state_entropy': round(self.state_entropy, 4),
            'is_confidence_degraded': self.is_confidence_degraded
        }
