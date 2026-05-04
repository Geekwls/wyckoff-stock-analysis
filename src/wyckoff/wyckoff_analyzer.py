#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy compatibility module.

Historically callers imported `WyckoffAnalyzer` and `batch_scan` from
`src.wyckoff.wyckoff_analyzer`. The implementation moved to `facade.py`.
This module preserves that import path.
"""

from .facade import WyckoffAnalyzer, batch_scan

__all__ = ["WyckoffAnalyzer", "batch_scan"]
