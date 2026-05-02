from pydantic import BaseModel, Field, ConfigDict, field_validator
from dataclasses import dataclass

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
    
    # 高潮检测参数
    climax_vol_multiplier: float = Field(3.0, ge=2.0, le=10.0)
    climax_range_multiplier: float = Field(1.5, ge=1.0, le=5.0)
    
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

@dataclass
class WyckoffThresholds:
    """威科夫分析阈值集中配置"""
    SPRING_BREAKDOWN = {
        'low': 0.03,
        'medium': 0.04,
        'high': 0.05
    }
    VOLUME_CONFIRMATION = {
        'strong': 1.5,
        'moderate': 1.2,
        'weak': 0.8
    }
    CLOSE_POSITION_CONFIRMATION = 0.7
    RECOVERY_DAYS = 3
