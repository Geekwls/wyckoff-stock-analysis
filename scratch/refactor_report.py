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
        'generate_report', '_round_floats', 'calculate_signal_quality', 'generate_trading_plan',
        'get_relevant_terms', 'generate_risk_advice', 'generate_interactive_qa',
        'get_signal_performance', 'add_market_sentiment', 'generate_json'
    ]
    
    extracted_lines = [
        "import pandas as pd",
        "import numpy as np",
        "import json",
        "from typing import Dict, List, Optional, Any, Tuple",
        "from datetime import datetime",
        "from ..config.settings import WyckoffConfig",
        "import logging",
        "logger = logging.getLogger(__name__)",
        "",
        "class WyckoffReportGenerator:",
        "    def __init__(self, analyzer):",
        "        self.analyzer = analyzer",
        "        self.data = analyzer.data",
        "        self.config = analyzer.config",
        "        self.symbol = analyzer.symbol",
        "        self.pattern_detector = analyzer.pattern_detector",
        "        self.law_analyzer = analyzer.law_analyzer",
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
            
            # Now we replace references to `self.detect...` with `self.pattern_detector.detect...`
            # But wait, in the previous refactoring, they were already changed to `self.pattern_detector.detect...`!
            # Let's just preserve the lines, but we also need to change `self._get_cached_index_analyzer`
            # and other methods to `self.analyzer._get_cached_index_analyzer`.
            
            # Since ReportGenerator now has self.data, self.config, self.pattern_detector, self.law_analyzer, self.symbol
            # many `self.xxx` calls will still work.
            # But what about calls to `self.calculate_cause_effect`? It should be `self.analyzer.calculate_cause_effect`.
            # What about `self.analyze_timeframe_resonance`? -> `self.analyzer.analyze_timeframe_resonance`
            # Let's fix that via regex.
            
            for i, line in enumerate(method_lines):
                # Replace self.method() with self.analyzer.method() if method is not in our extracted list and not an attribute we have
                # A simple regex for self.xxx() calls
                for match in re.finditer(r'self\.([a-zA-Z0-9_]+)\(', line):
                    method_name = match.group(1)
                    if method_name not in methods_to_extract and method_name not in ['pattern_detector', 'law_analyzer', 'data', 'config']:
                        # It is calling an analyzer method
                        method_lines[i] = method_lines[i].replace(f'self.{method_name}(', f'self.analyzer.{method_name}(')
                        
            extracted_lines.extend(method_lines)
            extracted_lines.append("\n")
            
            for i in range(start, end):
                lines_to_remove.add(i)

    os.makedirs('tools/core', exist_ok=True)
    with open('tools/core/report_generator.py', 'w', encoding='utf-8') as f:
        f.write("".join(extracted_lines))
        
    new_lines = []
    for i, line in enumerate(lines):
        if i not in lines_to_remove:
            new_lines.append(line)
            
    new_source = "".join(new_lines)

    # Add import for ReportGenerator
    new_source = new_source.replace(
        "from tools.core.law_analyzer import WyckoffLawAnalyzer",
        "from tools.core.law_analyzer import WyckoffLawAnalyzer\n    from tools.core.report_generator import WyckoffReportGenerator"
    )
    
    new_source = new_source.replace(
        "from .core.law_analyzer import WyckoffLawAnalyzer",
        "from .core.law_analyzer import WyckoffLawAnalyzer\n    from .core.report_generator import WyckoffReportGenerator"
    )

    # Add generator stub methods to wyckoff_analyzer.py
    # Since generate_json and generate_report are the main entry points, we just add them back as wrappers.
    stubs = """
    def generate_report(self) -> str:
        from .core.report_generator import WyckoffReportGenerator
        return WyckoffReportGenerator(self).generate_report()
        
    def generate_json(self) -> str:
        from .core.report_generator import WyckoffReportGenerator
        return WyckoffReportGenerator(self).generate_json()
"""
    # Insert stubs at the end of the class
    new_source = new_source + stubs

    with open('tools/wyckoff_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(new_source)

if __name__ == '__main__':
    refactor()
