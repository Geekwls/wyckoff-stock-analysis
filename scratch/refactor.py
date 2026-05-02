import os
import ast
import re

def refactor():
    file_path = 'tools/wyckoff_analyzer.py'
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        source = "".join(lines)

    tree = ast.parse(source)
    class_node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'WyckoffAnalyzer')
    
    methods_to_extract = [
        'detect_trading_range', 'detect_spring', '_detect_spring_impl', 'detect_climax', '_detect_climax_impl',
        'detect_automatic_reaction', 'detect_secondary_test', 'detect_upthrust', '_detect_upthrust_impl',
        'detect_sos', '_detect_sos_impl', 'detect_sow', '_detect_sow_impl', 'detect_lps', 'detect_lpsy',
        'detect_sos_variants', 'detect_sow_variants', '_calculate_overall_sos_strength', '_calculate_overall_sow_strength',
        'detect_pattern_confirmation', '_check_spring_confirmation', '_check_sos_confirmation', '_check_upthrust_confirmation',
        '_calculate_reliability_score', 'detect_divergence', 'calculate_sequence_score', '_get_sequence_rating',
        'identify_phase', '_determine_phase_from_events', '_check_ma_confirmation', '_check_volume_confirmation',
        '_classify_volatility'
    ]
    
    extracted_lines = [
        "import pandas as pd",
        "import numpy as np",
        "from typing import Dict, List, Optional, Any",
        "from datetime import datetime",
        "from ..config.settings import WyckoffConfig, WyckoffThresholds",
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
        "class WyckoffPatternDetector:",
        "    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, analysis_cache):",
        "        self.data = data",
        "        self.config = config",
        "        self._analysis_cache = analysis_cache",
        ""
    ]
    
    lines_to_remove = set()
    
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef) and node.name in methods_to_extract:
            start = node.lineno - 1
            end = node.end_lineno
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            
            method_lines = lines[start:end]
            extracted_lines.extend(method_lines)
            extracted_lines.append("\n")
            
            for i in range(start, end):
                lines_to_remove.add(i)

    os.makedirs('tools/core', exist_ok=True)
    with open('tools/core/pattern_detector.py', 'w', encoding='utf-8') as f:
        f.write("".join(extracted_lines))
        
    new_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_remove:
            new_lines.append(line)
            
    new_source = "".join(new_lines)

    # Add import for PatternDetector
    new_source = new_source.replace(
        "from .core.data_fetcher import WyckoffDataFetcher",
        "from .core.data_fetcher import WyckoffDataFetcher\n    from .core.pattern_detector import WyckoffPatternDetector"
    )

    # Instantiate PatternDetector in fetch_data
    new_source = new_source.replace(
        "        self.data = data\n        return self.data",
        "        self.data = data\n        if self.data is not None:\n            self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)\n        return self.data"
    )

    # Initialize self.pattern_detector in __init__ just in case
    new_source = new_source.replace(
        "self.data = None",
        "self.data = None\n        self.pattern_detector = None"
    )

    # Replace method calls: self.detect_spring() -> self.pattern_detector.detect_spring()
    for method in methods_to_extract:
        if not method.startswith('_'):  # Only replace public method calls
            new_source = re.sub(r'self\.(' + method + r')\(', r'self.pattern_detector.\1(', new_source)

    # Some private methods might still be called from wyckoff_analyzer if they were not moved correctly or used externally
    new_source = new_source.replace('self._classify_volatility()', 'self.pattern_detector._classify_volatility()')
    new_source = new_source.replace('self.identify_phase(', 'self.pattern_detector.identify_phase(')

    with open('tools/wyckoff_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(new_source)

if __name__ == '__main__':
    refactor()
