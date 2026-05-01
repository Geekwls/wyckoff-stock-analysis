#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
兼容入口：威科夫可视化工具。

新代码请优先使用：
    from tools.visualization.wyckoff_visualizer import WyckoffVisualizer
"""

try:
    from tools.visualization.wyckoff_visualizer import *
except ImportError:
    from visualization.wyckoff_visualizer import *
