"""Backward-compatible wrapper for legacy import path.

Use `wyckoff.facade` instead.
"""

from wyckoff.facade import WyckoffAnalyzer, batch_scan
from wyckoff.config.settings import WyckoffConfig

__all__ = ["WyckoffAnalyzer", "WyckoffConfig", "batch_scan"]
