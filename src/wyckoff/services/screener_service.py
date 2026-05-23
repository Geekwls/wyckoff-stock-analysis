"""
威科夫分析系统 - 筛选服务
统一的股票筛选服务，整合快速扫描和深度筛选
"""
import concurrent.futures
from typing import List, Dict, Optional, Any
import logging
import os
import pandas as pd

from ..facade import WyckoffAnalyzer
from ..config.settings import WyckoffConfig
from ..exceptions import AnalysisError, DataError, CalculationError, PatternNotFoundError
from ..core.recommendation_engine import RecommendationEngine
from ..core.enums import MarketEnvironment
from ..core.utils import PhaseAdapter
from ..core.cache_service import IndexDataCache

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
        self._index_cache = IndexDataCache()  # P1.1: 全局指数数据缓存
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
                        
                except (DataError, CalculationError) as exc:
                    logger.warning("quick_scan: 数据/计算错误跳过 %s: %s", futures[future], exc)
                    failed_symbols.append(f"{futures[future]}: DataError/CalculationError - {exc}")
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
        扫描单个股票 (P1.1: 使用共享指数缓存)
        
        Args:
            symbol: 股票代码
            period: 数据周期
            
        Returns:
            扫描结果
        """
        try:
            analyzer = WyckoffAnalyzer(
                symbol, period, self.config,
                index_data_cache=self._index_cache  # P1.1: 注入共享缓存
            )
            
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
                'is_late_stage': PhaseAdapter.is_late_stage(phase_res.get('phase_enum'))
            }
            
        except (DataError, CalculationError) as exc:
            raise DataError(f"扫描 {symbol} 失败: {str(exc)}", symbol=symbol) from exc
        except Exception as exc:
            raise AnalysisError(f"扫描 {symbol} 失败: {str(exc)}") from exc
    
    def _load_stocks(self, symbols: List[str], period: str):
        """加载股票数据 (P1.1: 使用共享指数缓存)"""
        self._analyzers.clear()
        self._index_cache.clear()

        # 预加载常用指数数据
        common_indices = ["sh.000001", "sz.399001", "sz.399006", "sh.000688"]
        for idx_symbol in common_indices:
            self._prefetch_index_if_needed(idx_symbol, period)
        
        for symbol in symbols:
            try:
                analyzer = WyckoffAnalyzer(
                    symbol, period, self.config,
                    index_data_cache=self._index_cache  # P1.1: 注入共享缓存
                )
                if analyzer.fetch_data() is not None:
                    self._analyzers[symbol] = analyzer
            except (DataError, CalculationError) as e:
                logger.warning("加载 %s 失败 (数据/计算错误): %s", symbol, e)
            except Exception as e:
                logger.warning("加载 %s 失败: %s", symbol, e)

    def _prefetch_index_if_needed(self, index_symbol: str, period: str):
        """预加载指数数据（如果缓存中不存在）"""
        if self._index_cache.get_index_data(index_symbol, period) is None:
            try:
                from ..core.data_fetcher import WyckoffDataFetcher
                fetcher = WyckoffDataFetcher(self.config)
                resolved, data = fetcher.fetch_data(index_symbol, period)
                if data is not None and not data.empty:
                    self._index_cache.set_index_data(resolved, period, data)
                    logger.info(f"指数数据预加载: {resolved}")
            except Exception as e:
                logger.debug(f"指数预加载跳过 {index_symbol}: {e}")
    
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
            is_late_stage = PhaseAdapter.is_late_stage(phase_enum or phase_str)
            if final_score < 40 and not is_late_stage:
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
                'is_late_stage': is_late_stage,
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
            is_late_stage = PhaseAdapter.is_late_stage(phase_enum or phase_str)
            if final_score < 40 and not is_late_stage:
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
                'is_late_stage': is_late_stage,
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
            trading_range = analyzer.pattern_detector.detect_trading_range()
            spring = analyzer.pattern_detector.detect_spring_menhongtao()
            sos = analyzer.pattern_detector.detect_sos()
            joc = analyzer.pattern_detector.detect_joc_menhongtao()
            lps = analyzer.pattern_detector.detect_lps(
                sos,
                spring,
                trading_range=trading_range,
                joc_result=joc,
            )
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
            
            entry_tag = " [LATE_STAGE]" if result.get('is_late_stage') else ""
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
        late_stage_count = sum(1 for r in results if r.get('is_late_stage', False))
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
            "entry_count": signal_count,  # 保持对旧客户端及测试代码的向后兼容性
            "late_stage_count": late_stage_count,
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

    def screen_spring(
        self,
        symbols: List[str] = None,
        period: str = "1y",
        min_market_cap: float = 10e8,
        min_daily_amount: float = 1e8,
        max_workers: int = 1,
        show_progress: bool = True,
    ) -> Dict[str, Any]:
        """
        全市场 Spring 筛选（孟洪涛 5 重过滤）
        
        注意：baostock 不支持高并发请求，建议使用 max_workers=1 或 2。
        多线程可能导致数据获取失败。
        
        Args:
            symbols: 股票代码列表，None 则自动获取全 A 股
            period: 数据周期
            min_market_cap: 最小市值（元），默认 10 亿
            min_daily_amount: 最小日成交额（元），默认 1 亿
            max_workers: 并行线程数（默认 1，baostock 并发能力有限）
            show_progress: 显示进度
        
        Returns:
            筛选结果字典
        """
        from tqdm import tqdm
        from ..core.stock_data_provider import StockDataProvider
        
        # 1. 获取股票池
        if symbols is None:
            symbols = StockDataProvider.filter_stocks(
                min_market_cap=min_market_cap,
                min_daily_amount=min_daily_amount
            )
        
        # 2. 获取全量数据（用于市值、行业查询）
        stock_info = StockDataProvider.get_all_a_shares_with_info()
        
        if show_progress:
            print(f"[Spring 筛选] 开始扫描 {len(symbols)} 只股票...")
        
        # 3. 并行扫描
        results = []
        failed = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._scan_single_spring_enhanced, sym, period, stock_info
                ): sym
                for sym in symbols
            }
            
            for future in tqdm(
                concurrent.futures.as_completed(futures),
                total=len(symbols),
                desc="Spring 筛选",
                disable=not show_progress
            ):
                try:
                    result = future.result()
                    if result and result.get('spring_detected'):
                        results.append(result)
                except Exception as e:
                    failed.append(str(e))
        
        # 4. 按确认状态和置信度排序
        results.sort(key=lambda x: (
            0 if x.get('confirmation') == 'confirmed' else 1,
            -x.get('confidence', 0)
        ))
        
        # 5. 显示统计信息
        if show_progress:
            confirmed = sum(1 for r in results if r.get('confirmation') == 'confirmed')
            pending = sum(1 for r in results if r.get('confirmation') == 'pending')
            print(f"\n[Spring 筛选完成]")
            print(f"  扫描总数: {len(symbols)}")
            print(f"  发现 Spring: {len(results)}")
            print(f"  已确认: {confirmed}")
            print(f"  待确认: {pending}")
            print(f"  失败: {len(failed)}")
        
        return {
            'results': results,
            'summary': {
                'total_scanned': len(symbols),
                'spring_count': len(results),
                'confirmed_count': sum(
                    1 for r in results if r.get('confirmation') == 'confirmed'
                ),
                'pending_count': sum(
                    1 for r in results if r.get('confirmation') == 'pending'
                ),
                'failed_count': len(failed)
            }
        }
    
    def _scan_single_spring_enhanced(
        self, symbol: str, period: str, stock_info: pd.DataFrame
    ) -> Optional[Dict]:
        """扫描单只股票的 Spring 信号（孟洪涛 5 重过滤）
        
        使用 akshare 获取历史数据（比 baostock 快 10 倍）
        """
        try:
            # 获取股票信息
            code = symbol.split('.')[1] if '.' in symbol else symbol
            info_row = stock_info[stock_info['code'] == code]
            if info_row.empty:
                return None
            info = info_row.iloc[0]
            
            # 使用 akshare 直接获取历史数据（绕过 baostock，速度快）
            from ..core.strategies.akshare_strategy import AkShareStrategy
            from ..core.data_fetcher import prepare_data
            
            ak_strategy = AkShareStrategy(self.config)
            raw_data = ak_strategy.fetch(symbol, period)
            if raw_data is None or raw_data.empty:
                return None
            
            # 准备数据（计算技术指标）
            data = prepare_data(raw_data, self.config)
            
            # 创建 WyckoffPatternDetector（不调用 fetch_data，直接用准备好的数据）
            from ..core.pattern_detector import WyckoffPatternDetector
            from ..core.cache import LRUCache
            pattern_detector = WyckoffPatternDetector(data, self.config, LRUCache())
            
            # 孟洪涛 5 重过滤 Spring 检测
            spring_result = pattern_detector.meng_enhancer.detect_spring_enhanced()
            
            if not spring_result.get('detected'):
                return None
            
            # 获取最新 Spring 信号
            latest = spring_result.get('latest_spring', {})
            if not latest:
                return None
            
            # 检查确认状态
            confirmation_status = self._check_spring_confirmation_from_data(
                latest, data
            )
            
            # 计算 RS 强度
            rs_data = self._calculate_rs_from_data(symbol, data)
            
            return {
                'symbol': symbol,
                'name': info.get('name', ''),
                'industry': info.get('industry', ''),
                'market_cap': info.get('market_cap', 0),
                'market_cap_yi': round(info.get('market_cap', 0) / 1e8, 2),
                'daily_amount': info.get('amount', 0),
                'daily_amount_wan': round(info.get('amount', 0) / 1e4, 2),
                'rs_trend': rs_data.get('rs_trend', 'unknown'),
                'rs_change_20d': rs_data.get('rs_change_20d', 0),
                'spring_detected': True,
                'spring_date': str(latest.get('date', '')),
                'support_level': latest.get('support_level'),
                'recovery_price': latest.get('recovery_price'),
                'volume_ratio': latest.get('vol_ratio'),
                'confidence': latest.get('confidence', 0),
                'recovery_days': latest.get('recovery_days'),
                'confirmation': confirmation_status['status'],
                'confirmation_reason': confirmation_status['reason'],
                'current_price': data['Close'].iloc[-1],
                'distance_to_support': self._calc_distance_to_support(
                    data['Close'].iloc[-1], latest.get('support_level', 0)
                )
            }
        except Exception as e:
            logger.warning(f"扫描 {symbol} Spring 失败: {e}")
            return None
    
    def _check_spring_confirmation_from_data(
        self, spring_signal: Dict, data: pd.DataFrame
    ) -> Dict[str, str]:
        """检查 Spring 信号的确认状态（直接使用数据）"""
        try:
            from ..core.signal_lifecycle import build_snapshot, check_confirmation
            
            snap = build_snapshot(
                signal_type="spring",
                price=spring_signal.get('recovery_price', 0),
                low=spring_signal.get('breakdown_price', 0),
                high=data['High'].iloc[-1],
                volume=data['Volume'].iloc[-1],
                support=spring_signal.get('support_level', 0),
                resistance=data['High'].rolling(20).max().iloc[-1]
            )
            
            today_low = data['Low'].iloc[-1]
            today_high = data['High'].iloc[-1]
            today_close = data['Close'].iloc[-1]
            today_volume = data['Volume'].iloc[-1]
            
            spring_date = spring_signal.get('date')
            if spring_date:
                try:
                    signal_dt = pd.to_datetime(spring_date)
                    days_elapsed = (pd.Timestamp.now() - signal_dt).days
                except Exception:
                    days_elapsed = 0
            else:
                days_elapsed = 0
            
            status, reason = check_confirmation(
                "spring", snap, today_low, today_high, today_close, today_volume, days_elapsed
            )
            
            return {'status': status, 'reason': reason}
        except Exception as e:
            logger.warning(f"检查 Spring 确认状态失败: {e}")
            return {'status': 'unknown', 'reason': str(e)}
    
    def _calculate_rs_from_data(self, symbol: str, data: pd.DataFrame) -> Dict:
        """计算 RS 强度（直接使用数据）"""
        try:
            from ..core.relative_strength_analyzer import RelativeStrengthAnalyzer
            from ..facade import WyckoffAnalyzer
            
            # 获取基准指数
            temp_analyzer = WyckoffAnalyzer.__new__(WyckoffAnalyzer)
            temp_analyzer.symbol = symbol
            temp_analyzer.config = self.config
            idx_symbol = temp_analyzer._get_baseline_index_symbol()
            
            # 用 akshare 获取基准数据
            from ..core.strategies.akshare_strategy import AkShareStrategy
            from ..core.data_fetcher import prepare_data
            ak_strategy = AkShareStrategy(self.config)
            idx_raw = ak_strategy.fetch(idx_symbol, "1y")
            idx_data = prepare_data(idx_raw, self.config)
            
            rs_analyzer = RelativeStrengthAnalyzer(data, symbol)
            rs_data = rs_analyzer.calculate_rs(idx_data)
            return rs_data
        except Exception as e:
            logger.warning(f"计算 RS 失败: {e}")
            return {'rs_trend': 'unknown', 'rs_change_20d': 0}
    
    @staticmethod
    def _calc_distance_to_support(current_price: float, support_level: float) -> float:
        """计算当前价格距支撑位的距离百分比"""
        if support_level <= 0:
            return 0.0
        return round((current_price - support_level) / support_level * 100, 2)


def format_spring_results_table(results: List[Dict], max_rows: int = 50) -> str:
    """格式化 Spring 筛选结果为实用表格"""
    if not results:
        return "未找到 Spring 信号"
    
    # 表头
    header = (
        f"{'代码':<10} {'名称':<8} {'行业':<8} {'市值(亿)':>8} "
        f"{'RS强度':>6} {'支撑位':>8} {'当前价':>8} {'距支撑%':>8} "
        f"{'量比':>6} {'置信度':>6} {'确认':>4}"
    )
    separator = "=" * 100
    
    lines = [separator, header, separator]
    
    for r in results[:max_rows]:
        symbol = r.get('symbol', '')
        name = r.get('name', '')[:4]  # 截取前 4 个字符
        industry = r.get('industry', '')[:4]
        market_cap = f"{r.get('market_cap_yi', 0):.0f}"
        
        rs_trend = r.get('rs_trend', 'unknown')
        rs_mark = '↑' if rs_trend == 'rising' else '↓' if rs_trend == 'falling' else '→'
        
        support = f"{r.get('support_level', 0):.2f}"
        current = f"{r.get('current_price', 0):.2f}"
        distance = f"{r.get('distance_to_support', 0):.1f}%"
        vol_ratio = f"{r.get('volume_ratio', 0):.2f}"
        confidence = f"{r.get('confidence', 0):.0f}%"
        
        confirmation = r.get('confirmation', 'unknown')
        conf_mark = '✅' if confirmation == 'confirmed' else '⏳' if confirmation == 'pending' else '❌'
        
        line = (
            f"{symbol:<10} {name:<8} {industry:<8} {market_cap:>8} "
            f"{rs_mark:>4} {support:>8} {current:>8} {distance:>8} "
            f"{vol_ratio:>6} {confidence:>6} {conf_mark:>4}"
        )
        lines.append(line)
    
    lines.append(separator)
    
    # 统计信息
    confirmed = sum(1 for r in results if r.get('confirmation') == 'confirmed')
    pending = sum(1 for r in results if r.get('confirmation') == 'pending')
    lines.append(
        f"总计: {len(results)} 只 Spring | "
        f"已确认: {confirmed} | 待确认: {pending}"
    )
    
    return "\n".join(lines)


# 预定义股票池已迁移至 src/wyckoff/stock_pools.py
try:
    from ..stock_pools import STOCK_POOLS
except ImportError:
    STOCK_POOLS = {}
