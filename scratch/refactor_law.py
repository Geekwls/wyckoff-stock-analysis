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
        'analyze_supply_demand_law', 'analyze_effort_vs_result_law', 'analyze_cause_effect_law_enhanced',
        '_detect_preliminary_support', '_detect_preliminary_supply', '_analyze_absorption_pattern',
        '_analyze_exhaustion_pattern', '_calculate_breakout_probability'
    ]
    
    extracted_lines = [
        "import pandas as pd",
        "import numpy as np",
        "from typing import Dict, List, Optional, Any, Tuple",
        "from datetime import datetime",
        "from ..config.settings import WyckoffConfig",
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
        "class WyckoffLawAnalyzer:",
        "    def __init__(self, data: pd.DataFrame, config: WyckoffConfig, pattern_detector):",
        "        self.data = data",
        "        self.config = config",
        "        self.pattern_detector = pattern_detector",
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
    with open('tools/core/law_analyzer.py', 'w', encoding='utf-8') as f:
        f.write("".join(extracted_lines))
        
    new_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_remove:
            new_lines.append(line)
            
    new_source = "".join(new_lines)

    # Add import for LawAnalyzer
    new_source = new_source.replace(
        "from tools.core.pattern_detector import WyckoffPatternDetector",
        "from tools.core.pattern_detector import WyckoffPatternDetector\n    from tools.core.law_analyzer import WyckoffLawAnalyzer"
    )
    
    new_source = new_source.replace(
        "from .core.pattern_detector import WyckoffPatternDetector",
        "from .core.pattern_detector import WyckoffPatternDetector\n    from .core.law_analyzer import WyckoffLawAnalyzer"
    )

    # Instantiate LawAnalyzer in fetch_data
    new_source = new_source.replace(
        "self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)",
        "self.pattern_detector = WyckoffPatternDetector(self.data, self.config, self._analysis_cache)\n            self.law_analyzer = WyckoffLawAnalyzer(self.data, self.config, self.pattern_detector)"
    )

    # Replace method calls
    for method in methods_to_extract:
        if not method.startswith('_'):
            new_source = re.sub(r'self\.(' + method + r')\(', r'self.law_analyzer.\1(', new_source)

    with open('tools/wyckoff_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(new_source)

if __name__ == '__main__':
    refactor()
