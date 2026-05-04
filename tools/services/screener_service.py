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
from ..core.recommendation_engine import RecommendationEngine
from ..core.utils import PhaseAdapter

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
        self.rec_engine = RecommendationEngine(self.config)
    
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
            
            # 提取信号 (使用新引擎)
            strength = RecommendationEngine.calculate_signal_strength(phase_res)
            # 注意：此处 market_env 为占位，未来可通过 orchestrator 获取
            quality = self.rec_engine.calculate_signal_quality(data, phase_res, MarketEnvironment.UNKNOWN)
            
            return {
                'symbol': symbol,
                'phase': phase_str,
                'confidence': round((phase_res.get('confidence') or 0.0) if isinstance(phase_res, dict) else 0.0, 2),
                'strength': strength,
                'weighted_score': quality.score,
                'is_entry': PhaseAdapter.is_entry_phase(phase_res.get('phase_enum'))
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
        """筛选处于积累期（特别是 C/D 阶段）的股票"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = phase_res.get('phase', 'Unknown')
            phase_enum = phase_res.get('phase_enum')
            
            if not PhaseAdapter.is_accumulation(phase_str):
                continue
            
            # 个股加权分
            market_data = analyzer.get_market_regime()
            quality = self.rec_engine.calculate_signal_quality(analyzer.data, phase_res, market_data['regime'])
            stock_score = quality.score
            
            # 市场门控
            industry_mult = analyzer.get_industry_multiplier()
            final_score = stock_score * market_data['multiplier'] * industry_mult
            
            # 过滤
            is_entry = PhaseAdapter.is_entry_phase(phase_enum or phase_str)
            if final_score < 40 and not is_entry:
                continue
                
            # 计算可执行性得分
            tr = analyzer.pattern_detector.detect_trading_range()
            exec_score = RecommendationEngine.get_execution_score(
                analyzer.data['Close'].iloc[-1], tr['low'], tr['high'], "做多"
            )
            
            results.append({
                'symbol': symbol,
                'phase': phase_str,
                'phase_detail': phase_enum.name if phase_enum else 'Unknown',
                'raw_score': stock_score,
                'final_score': round(final_score, 2),
                'market_regime': market_data['regime'],
                'is_entry_stage': is_entry,
                'execution_score': exec_score,
                'trading_range': tr,
                'current_price': analyzer.data['Close'].iloc[-1],
                'confidence': phase_res.get('confidence', 0)
            })
        
        # 按最终得分 * 可执行性综合排序
        results.sort(key=lambda x: x['final_score'] * (x['execution_score']/100 + 0.5), reverse=True)
        return results
    
    def _screen_distribution(self) -> List[Dict]:
        """筛选处于派发期（特别是 C/D 阶段）的股票"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = phase_res.get('phase', 'Unknown')
            phase_enum = phase_res.get('phase_enum')
            
            if not PhaseAdapter.is_distribution(phase_str):
                continue
            
            # 个股加权分
            market_data = analyzer.get_market_regime()
            quality = self.rec_engine.calculate_signal_quality(analyzer.data, phase_res, market_data['regime'])
            stock_score = quality.score
            
            # 市场门控
            multiplier = 1.2 if market_data['regime'] == 'risk-off' else 0.8 if market_data['regime'] == 'risk-on' else 1.0
            final_score = stock_score * multiplier
            
            # 过滤
            is_entry = PhaseAdapter.is_entry_phase(phase_enum or phase_str)
            if final_score < 40 and not is_entry:
                continue
            
            tr = analyzer.pattern_detector.detect_trading_range()
            exec_score = RecommendationEngine.get_execution_score(
                analyzer.data['Close'].iloc[-1], tr['low'], tr['high'], "做空"
            )
            
            results.append({
                'symbol': symbol,
                'phase': phase_str,
                'phase_detail': phase_enum.name if phase_enum else 'Unknown',
                'raw_score': stock_score,
                'final_score': round(final_score, 2),
                'is_entry_stage': is_entry,
                'execution_score': exec_score,
                'trading_range': tr,
                'current_price': analyzer.data['Close'].iloc[-1]
            })
        
        results.sort(key=lambda x: x['final_score'], reverse=True)
        return results
    
    def _screen_lps_entries(self) -> List[Dict]:
        """筛选LPS入场机会"""
        results = []
        
        for symbol, analyzer in self._analyzers.items():
            lps = analyzer.pattern_detector.detect_lps()
            if not lps.get('detected'):
                continue
            
            phase_res = analyzer.identify_phase_with_rs()
            phase_str = phase_res.get('phase', 'Unknown')
            
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
            phase_str = phase_res.get('phase', 'Unknown')
            
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
        # 注意：此处 result 现在直接包含标志位，由调用者决定
        if result.get('has_lps'):      icons.append('LPS')
        if result.get('has_upthrust'): icons.append('Upthrust')
        if result.get('has_lpsy'):     icons.append('LPSY')
        if result.get('has_sos'):      icons.append('SOS')
        if result.get('has_sow'):      icons.append('SOW')
        
        if icons:
            strength_str = f"强度{result['strength']}/6"
            if 'weighted_score' in result:
                strength_str = f"综合评分:{result['weighted_score']}"
            
            entry_tag = " [ENTRY]" if result.get('is_entry') else ""
            print(f"  [OK] {result['symbol']}: [{result['phase']}] {' | '.join(icons)} ({strength_str}){entry_tag}")
    
    def _print_summary(self, results: List[Dict], failed_symbols: List[str], symbols: List[str]):
        """显示统计信息"""
        print(f"\n[SUMMARY] 扫描完成:")
        print(f"  成功: {len(results)}/{len(symbols)}")
        if failed_symbols:
            print(f"  失败: {len(failed_symbols)} ({', '.join(failed_symbols[:5])}{'...' if len(failed_symbols) > 5 else ''})")
        
        # 按信号强度排序
        top_signals = sorted(results, key=lambda x: x.get('weighted_score', x.get('strength', 0)), reverse=True)[:5]
        if top_signals and (top_signals[0].get('strength', 0) > 0 or top_signals[0].get('weighted_score', 0) > 0):
            print(f"\n[TOP] 信号强度 TOP 5:")
            for i, stock in enumerate(top_signals, 1):
                score_str = f"评分:{stock['weighted_score']}" if 'weighted_score' in stock else f"强度{stock['strength']}/6"
                print(f"  {i}. {stock['symbol']} - {stock['phase']} ({score_str})")


    def batch_scan(self, symbols: List[str], period: str = "1y",
                   scan_mode: str = "quick", **kwargs) -> Dict[str, Any]:
        """
        批量扫描（统一入口）

        Args:
            symbols: 股票代码列表
            period: 数据周期
            scan_mode: 扫描模式
                - "quick": 快速扫描（并行，返回摘要）
            **kwargs: 额外参数
                - max_workers: 最大并行线程数（quick模式）
                - show_progress: 是否显示进度（默认True）
                - min_score: 最低评分过滤（默认0）

        Returns:
            扫描结果字典:
            {
                "results": List[Dict],  # 扫描结果列表
                "summary": Dict,         # 统计摘要
                "top_picks": List[Dict], # 顶级机会
                "failed": List[str]      # 失败的股票
            }

        Examples:
            >>> screener = ScreenerService()
            >>> result = screener.batch_scan(["AAPL", "MSFT"], scan_mode="quick")
        """
        logger.info(f"启动批量扫描: {len(symbols)} 只股票, 模式={scan_mode}")

        # 当前只支持 quick 模式
        if scan_mode == "quick":
            results = self.quick_scan(symbols, period, **kwargs)
            failed = [r.get('symbol', 'unknown') for r in results if 'error' in r]
            return self._format_batch_results(results, failed, scan_mode)
        else:
            raise ValueError(
                f"不支持的扫描模式: {scan_mode}。"
                f"当前仅支持 'quick' 模式。"
                f"其他模式（accumulation/distribution/lps/lpsy）需要适配新版 WyckoffAnalyzer 接口。"
            )

    def _format_batch_results(self, results: List[Dict], failed: List[str],
                              scan_mode: str) -> Dict[str, Any]:
        """
        格式化批量扫描结果

        Args:
            results: 扫描结果列表
            failed: 失败的股票列表
            scan_mode: 扫描模式

        Returns:
            格式化的结果字典
        """
        # 计算统计信息
        total_scanned = len(results)
        signal_count = sum(1 for r in results if r.get('strength', 0) >= 1)
        entry_count = sum(1 for r in results if r.get('is_entry', False))
        high_score_count = sum(1 for r in results if r.get('weighted_score', 0) >= 60)

        # 找出顶级机会（按评分排序）
        top_picks = sorted(
            results,
            key=lambda x: x.get('weighted_score', x.get('strength', 0)),
            reverse=True
        )[:10]

        # 按阶段分组
        phase_groups = {}
        for r in results:
            phase = r.get('phase', 'Unknown')
            if phase not in phase_groups:
                phase_groups[phase] = []
            phase_groups[phase].append(r.get('symbol', 'unknown'))

        summary = {
            "total_scanned": total_scanned,
            "signal_count": signal_count,
            "entry_count": entry_count,
            "high_score_count": high_score_count,
            "failed_count": len(failed),
            "phase_distribution": {k: len(v) for k, v in phase_groups.items()}
        }

        return {
            "results": results,
            "summary": summary,
            "top_picks": top_picks,
            "failed": failed,
            "scan_mode": scan_mode
        }


# 预定义股票池已迁移至 tools/wyckoff_utils.py
try:
    from ..wyckoff_utils import STOCK_POOLS
except ImportError:
    STOCK_POOLS = {}
