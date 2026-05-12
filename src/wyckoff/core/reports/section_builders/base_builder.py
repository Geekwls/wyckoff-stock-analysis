from typing import Dict, Any

class BaseSectionBuilder:
    """报告区块构建基类"""
    def __init__(self, generator):
        self.generator = generator
        self.analyzer = generator.analyzer
        self.data = generator.data
        self.config = generator.config
        self.symbol = generator.symbol
        self.pattern_detector = generator.pattern_detector
        self.thresholds = generator.thresholds

    def build(self, **kwargs) -> str:
        raise NotImplementedError
