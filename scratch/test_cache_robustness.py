import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

import pandas as pd
from wyckoff.core.indicator_cache import IndicatorCache

def test_cache_collision():
    print("Testing IndicatorCache key collision protection...")
    df = pd.DataFrame({
        'Open': [1, 2], 'High': [2, 3], 'Low': [0, 1], 'Close': [1, 2], 'Volume': [100, 200]
    })
    cache = IndicatorCache(df)
    
    # Key for window=20 (int)
    key1 = cache._make_cache_key("MA", window=20)
    # Key for window="20" (str)
    key2 = cache._make_cache_key("MA", window="20")
    
    print(f"Key 1 (int): {key1}")
    print(f"Key 2 (str): {key2}")
    
    assert key1 != key2, "Cache collision detected between int and str parameters!"
    
    # Test sorting
    key3 = cache._make_cache_key("MA", a=1, b=2)
    key4 = cache._make_cache_key("MA", b=2, a=1)
    assert key3 == key4, "Cache key should be independent of parameter order!"
    
    print("IndicatorCache tests passed!")

if __name__ == "__main__":
    test_cache_collision()
