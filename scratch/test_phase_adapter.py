import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from wyckoff.core.utils import PhaseAdapter
from wyckoff.core.enums import WyckoffPhase

def test_phase_adapter():
    print("Testing PhaseAdapter...")
    
    # Test string input
    assert PhaseAdapter.is_accumulation("Accumulation Phase A") == True
    assert PhaseAdapter.is_accumulation("Distribution Phase A") == False
    assert PhaseAdapter.is_accumulation("\u5efa\u4ed3\u9636\u6bb5") == True # 建仓阶段
    
    # Test WyckoffPhase enum input
    # Currently PHASE_A is just "Phase A", so it should still return False
    # unless we changed WyckoffPhase (which we didn't).
    # But it should no longer be a hardcoded False.
    print(f"PHASE_A is_accumulation: {PhaseAdapter.is_accumulation(WyckoffPhase.PHASE_A)}")
    assert PhaseAdapter.is_accumulation(WyckoffPhase.PHASE_A) == False
    
    # Test custom enum with accumulation in value
    from enum import Enum
    class CustomPhase(Enum):
        ACC = "Accumulation Stage"
        DIST = "Distribution Stage"
        
    assert PhaseAdapter.is_accumulation(CustomPhase.ACC) == True
    assert PhaseAdapter.is_distribution(CustomPhase.DIST) == True
    
    # Test phase C/D
    assert PhaseAdapter.is_phase_c(WyckoffPhase.PHASE_C) == True
    assert PhaseAdapter.is_phase_d(WyckoffPhase.PHASE_D) == True
    assert PhaseAdapter.is_late_stage(WyckoffPhase.PHASE_C) == True
    assert PhaseAdapter.is_late_stage(WyckoffPhase.PHASE_D) == True
    
    print("All PhaseAdapter tests passed!")

if __name__ == "__main__":
    test_phase_adapter()
