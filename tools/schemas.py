from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class BasicDataModel(BaseModel):
    current_price: float
    volume: int
    volume_ratio: float

class MultiTimeframeModel(BaseModel):
    weekly_trend: str
    monthly_trend: str
    agreement: str

class ReportModel(BaseModel):
    symbol: str
    date: str
    phase: str
    phase_confidence: float
    sequence_score: Dict[str, Any] = Field(default_factory=dict)
    divergence: Dict[str, Any] = Field(default_factory=dict)
    multi_timeframe: MultiTimeframeModel
    relative_strength: Dict[str, Any] = Field(default_factory=dict)
    basic_data: BasicDataModel
    events: Dict[str, Any] = Field(default_factory=dict)
    cause_effect: Dict[str, Any] = Field(default_factory=dict)
    market_context: Dict[str, Any] = Field(default_factory=dict)
    global_sentiment: Dict[str, Any] = Field(default_factory=dict)
    signal_quality: Dict[str, Any] = Field(default_factory=dict)
    trading_plan: Dict[str, Any] = Field(default_factory=dict)
    wyckoff_laws: Dict[str, Any] = Field(default_factory=dict)
    terminology_guide: Dict[str, Any] = Field(default_factory=dict)
    risk_specific_advice: Dict[str, Any] = Field(default_factory=dict)
    interactive_qa: List[str] = Field(default_factory=list)
    performance_tracking: Dict[str, Any] = Field(default_factory=dict)
