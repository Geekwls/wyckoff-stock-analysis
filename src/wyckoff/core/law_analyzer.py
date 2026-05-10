import pandas as pd
import logging
from ..config.settings import WyckoffConfig
from .laws.supply_demand import SupplyDemandMixin
from .laws.effort_result import EffortResultMixin
from .laws.cause_effect import CauseEffectMixin

logger = logging.getLogger(__name__)


class WyckoffLawAnalyzer(SupplyDemandMixin, EffortResultMixin, CauseEffectMixin):
    """
    威科夫三大定律分析器（Facade）

    方法分散在 laws/ 下的三个 Mixin 中：
    - SupplyDemandMixin  → 第一定律（供求）
    - EffortResultMixin  → 第二定律（努力 vs 结果）
    - CauseEffectMixin   → 第三定律（因果）
    """

    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, pattern_detector):
        self.data = data
        self.config = config
        self.pattern_detector = pattern_detector
