"""
威科夫分析系统 - 筛选服务
统一的股票筛选服务，整合快速扫描和深度筛选
"""
import concurrent.futures
from typing import List, Dict, Optional, Any
import logging
import os

from ..wyckoff_analyzer import WyckoffAnalyzer
from ..config.settings import WyckoffConfig
from ..exceptions import AnalysisError
from ..core.signal_extractor import SignalExtractor

logger = logging.getLogger(__name__)


class ScreenerService:
    """
    统一的筛选服务
    
    提供两种筛选模式：
    1. 快速扫描（quick_scan）：并行扫描，返回摘要信息
    2. 深度筛选（deep_screen）：完整分析，返回详细报告
    """
    
    def __init__(self, config: WyckoffConfig = None):
        """
        初始化筛选服务
        
        Args:
            config: 威科夫配置
        """
        self.config = config or WyckoffConfig()
        self._analyzers: Dict[str, WyckoffAnalyzer] = {}
    
    def quick_scan(self, symbols: List[str], period: str = "1y",
                   max_workers: int = None, show_progress: bool = True) -> List[Dict]:
        """
        快速扫描（并行）
        
        Args:
            symbols: 股票代码列表
            period: 数据周期
            max_workers: 最大并行线程数
            show_progress: 是否显示进度
            
        Returns:
            扫描结果列表
        """
        from tqdm import tqdm
        
        if max_workers is None:
            max_workers = min(os.cpu_count() or 4, 8)
        
        results = []
        failed_symbols = []
        
        # 缓存清理间隔
        CACHE_CLEANUP_INTERVAL = 50
        
        if show_progress:
            print(f"[PARALLEL] 开始并行扫描 {len(symbols)} 只股票 (使用 {max_workers} 线程)...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._scan_single, symbol, period): symbol
                for symbol in symbols
            }
            
            processed_count = 0
            
            for future in tqdm(concurrent.futures.as_completed(futures),
                              total=len(symbols),
                              desc="扫描进度",
                              disable=not show_progress):
                try:
                    result = future.result()
                    results.append(result)
                    processed_count += 1
                    
                    # 显示找到信号的股票
                    if result.get('strength', 0) >= 1:
                        self._print_signal(result)
                        
                except Exception as exc:
                    logger.warning("quick_scan: 跳过失败的股票: %s", exc)
                    failed_symbols.append(str(exc))
        
        # 显示统计信息
        if show_progress:
            self._print_summary(results, failed_symbols, symbols)
        
        return results
    
    def deep_screen(self, symbols: List[str], period: str = "1y",
                    screen_type: str = 'accumulation') -> List[Dict]:
        """
        深度筛选
        
        Args:
            symbols: 股票代码列表
            period: 数据周期
            screen_type: 筛选类型 ('accumulation', 'distribution', 'lps_entries', 'lpsy_entries')
            
        Returns:
            筛选结果列表
        """
        # 加载所有股票数据
        self._load_stocks(symbols, period)
        
        # 根据类型执行筛选
        if screen_type == 'accumulation':
            return self._screen_accumulation()
        elif screen_type == 'distribution':
            return self._screen_distribution()
        elif screen_type == 'lps_entries':
            return self._screen_lps_entries()
        elif screen_type == 'lpsy_entries':
            return self._screen_lpsy_entries()
        else:
            raise ValueError(f"不支持的筛选类型: {screen_type}")
    
    def _scan_single(self, symbol: str, period: str) -> Dict:
        """
        扫描单个股票
        
        Args:
            symbol: 股票代码
            period: 数据周期
            
        Returns:
            扫描结果
        """
        try:
            analyzer = WyckoffAnalyzer(symbol, period, self.config)
            
            data = analyzer.fetch_data()
            if data is None or data.empty:
                return {'symbol': symbol, 'error': 'data_fetch_failed', 'strength': 0}
            
            # 从 identify_phase 结果中提取事件
            phase_res = analyzer.pattern_detector.identify_phase()
            events = phase_res.get('events_detected', {})
            
            phase_str = (phase_res.get('phase') or 'Unknown') if isinstance(phase_res, dict) else str(phase_res)
            
            # 提取信号
            signals = SignalExtractor.extract_signals(phase_res)
            strength = SignalExtractor.calculate_signal_strength(signals)
            
            return {
                'symbol': symbol,
                'phase': phase_str,
                'confidence': round((phase_res.get('confidence') or 0.0) if isinstance(phase_res, dict) else 0.0, 2),
                'has_spring': signals['has_spring'],
                'has_upthrust': signals['has_upthrust'],
                'has_sos': signals['has_sos'],
                'has_sow': signals['has_sow'],
                'has_lps': signals['has_lps'],
                'has_lpsy': signals['has_lpsy'],
                'strength': strength,
            }
            
        except Exception as exc:
            raise AnalysisError(f"扫描 {symbol} 失败: {str(exc)}") from exc
    
    def _load_stocks(self, symbols: List[str], period: str):
        """加载股票数据"""
        self._analyzers.clear()
        
        for symbol in symbols:
            try:
                analyzer = WyckoffAnalyzer(symbol, period, self.config)
                if analyzer.fetch_data() is not None:
                    self._analyzers[symbol] = analyzer
            except Exception as e:
                logger.warning("加载 %s 失败: %s", symbol, e)
    
    def _screen_accumulation(self) -> List[Dict]:
        """筛选处于积累期的股票"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = SignalExtractor.get_phase_string(phase_res)
            
            if not SignalExtractor.is_accumulation_phase(phase_str):
                continue
            
            signals = SignalExtractor.extract_accumulation_signals(phase_res)
            score = SignalExtractor.calculate_signal_strength(signals)
            
            if score >= 3:
                trading_range = analyzer.pattern_detector.detect_trading_range()
                results.append({
                    'symbol': symbol,
                    'phase': phase_str,
                    'score': score,
                    'has_spring': signals['has_spring'],
                    'has_sos': signals['has_sos'],
                    'has_lps': signals['has_lps'],
                    'trading_range': trading_range,
                    'current_price': analyzer.data['Close'].iloc[-1]
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results
    
    def _screen_distribution(self) -> List[Dict]:
        """筛选处于分布期的股票"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = SignalExtractor.get_phase_string(phase_res)
            
            if not SignalExtractor.is_distribution_phase(phase_str):
                continue
            
            signals = SignalExtractor.extract_distribution_signals(phase_res)
            score = SignalExtractor.calculate_signal_strength(signals)
            
            if score >= 3:
                trading_range = analyzer.pattern_detector.detect_trading_range()
                results.append({
                    'symbol': symbol,
                    'phase': phase_str,
                    'score': score,
                    'has_upthrust': signals['has_upthrust'],
                    'has_sow': signals['has_sow'],
                    'has_lpsy': signals['has_lpsy'],
                    'trading_range': trading_range,
                    'current_price': analyzer.data['Close'].iloc[-1]
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results
    
    def _screen_lps_entries(self) -> List[Dict]:
        """筛选LPS入场机会"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            lps = analyzer.pattern_detector.detect_lps()
            if not lps.get('detected'):
                continue
            
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = SignalExtractor.get_phase_string(phase_res)
            
            results.append({
                'symbol': symbol,
                'phase': phase_str,
                'lps_price': lps.get('price'),
                'lps_date': str(lps.get('date')),
                'current_price': analyzer.data['Close'].iloc[-1]
            })
        
        return results
    
    def _screen_lpsy_entries(self) -> List[Dict]:
        """筛选LPSY入场机会"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            lpsy = analyzer.pattern_detector.detect_lpsy()
            if not lpsy.get('detected'):
                continue
            
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = SignalExtractor.get_phase_string(phase_res)
            
            results.append({
                'symbol': symbol,
                'phase': phase_str,
                'lpsy_price': lpsy.get('price'),
                'lpsy_date': str(lpsy.get('date')),
                'current_price': analyzer.data['Close'].iloc[-1]
            })
        
        return results
    
    def _print_signal(self, result: Dict):
        """显示信号信息"""
        icons = []
        if result.get('has_spring'):   icons.append('Spring')
        if result.get('has_lps'):      icons.append('LPS')
        if result.get('has_upthrust'): icons.append('Upthrust')
        if result.get('has_lpsy'):     icons.append('LPSY')
        if result.get('has_sos'):      icons.append('SOS')
        if result.get('has_sow'):      icons.append('SOW')
        
        if icons:
            print(f"  [OK] {result['symbol']}: [{result['phase']}] {' | '.join(icons)} (强度{result['strength']}/6)")
    
    def _print_summary(self, results: List[Dict], failed_symbols: List[str], symbols: List[str]):
        """显示统计信息"""
        print(f"\n[SUMMARY] 扫描完成:")
        print(f"  成功: {len(results)}/{len(symbols)}")
        if failed_symbols:
            print(f"  失败: {len(failed_symbols)} ({', '.join(failed_symbols[:5])}{'...' if len(failed_symbols) > 5 else ''})")
        
        # 按信号强度排序
        top_signals = sorted(results, key=lambda x: x.get('strength', 0), reverse=True)[:5]
        if top_signals and top_signals[0].get('strength', 0) > 0:
            print(f"\n[TOP] 信号强度 TOP 5:")
            for i, stock in enumerate(top_signals, 1):
                print(f"  {i}. {stock['symbol']} - {stock['phase']} (强度{stock['strength']}/6)")


# 预定义股票池已迁移至 tools/wyckoff_utils.py
try:
    from ..wyckoff_utils import STOCK_POOLS
except ImportError:
    STOCK_POOLS = {}
