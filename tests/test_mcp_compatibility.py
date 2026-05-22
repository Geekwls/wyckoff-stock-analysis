import json
from unittest.mock import patch
from src.wyckoff.mcp_server import analyze_stock_wyckoff
from src.wyckoff.exceptions import DataFetchError

def test_error_compatibility():
    """验证错误响应的向后兼容性"""
    # 模拟一个会触发错误的调用 (非法代码)
    with patch('src.wyckoff.mcp_server.WyckoffAnalyzer') as mock_analyzer:
        mock_analyzer.side_effect = DataFetchError(symbol="INVALID.SYMBOL", reason="Mock fetch error")
        result_json = analyze_stock_wyckoff("INVALID.SYMBOL")
        
    result = json.loads(result_json)
    
    # 验证新字段
    assert "error_code" in result
    assert "retriable" in result
    
    # 验证旧字段 (必须存在以防破坏现有工具)
    assert "error" in result
    assert "type" in result
    
    print("Compatibility test passed: Legacy 'error' and 'type' fields are present.")

if __name__ == "__main__":
    test_error_compatibility()
