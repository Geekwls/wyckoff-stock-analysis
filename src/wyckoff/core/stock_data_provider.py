"""
A 股数据提供器
获取全 A 股代码、市值、行业、成交额等基础数据
"""
import pandas as pd
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class StockDataProvider:
    """A 股基础数据提供器"""
    
    _cache: Optional[pd.DataFrame] = None
    
    @classmethod
    def get_all_a_shares_with_info(cls, force_refresh: bool = False) -> pd.DataFrame:
        """
        获取全 A 股基础信息（市值、行业、成交额等）
        
        优先使用 AkShare（提供实时完整的市值和成交额数据，更利于筛选），
        失败时回退到 BaoStock。
        
        Returns:
            DataFrame with columns:
            - code: 股票代码（如 "600519"）
            - name: 股票名称
            - market_cap: 总市值（元）
            - circulating_market_cap: 流通市值（元）
            - industry: 行业
            - amount: 当日成交额（元）
            - turnover_rate: 换手率
            - pe_ratio: 市盈率
        """
        if cls._cache is not None and not force_refresh:
            return cls._cache
        
        logger.info("正在获取全 A 股数据...")
        
        # 优先使用 AkShare（数据维度完整，包含实时市值、成交额、换手率）
        try:
            logger.info("优先使用 AkShare 获取全 A 股实时行情数据...")
            df_spot = cls._fetch_from_akshare()
            if df_spot is not None and not df_spot.empty:
                cls._cache = df_spot
                logger.info(f"获取完成（AkShare），共 {len(df_spot)} 只股票")
                return df_spot
        except Exception as e:
            logger.warning(f"AkShare 获取全 A 股数据失败: {e}")
        
        # 回退到 BaoStock
        try:
            logger.info("回退到 BaoStock 获取全 A 股数据...")
            df_spot = cls._fetch_from_baostock()
            if df_spot is not None and not df_spot.empty:
                cls._cache = df_spot
                logger.info(f"获取完成（BaoStock），共 {len(df_spot)} 只股票")
                return df_spot
        except Exception as e:
            logger.warning(f"BaoStock 获取全 A 股数据失败: {e}")
        
        # 两个数据源都失败，返回空 DataFrame
        logger.error("所有数据源获取全 A 股数据均失败")
        return pd.DataFrame()
    
    @classmethod
    def _fetch_from_baostock(cls) -> Optional[pd.DataFrame]:
        """通过 BaoStock 获取全 A 股数据"""
        try:
            import baostock as bs

            lg = bs.login()
            if lg.error_code != '0':
                logger.warning(f"BaoStock 登录失败: {lg.error_msg}")
                return None
            
            # 获取股票基本信息
            rs = bs.query_stock_basic()
            if rs.error_code != '0':
                logger.warning(f"BaoStock query_stock_basic 失败: {rs.error_msg}")
                return None
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if not data_list:
                return None
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 过滤：仅保留主板/创业板/科创板
            df = df[df['code'].str.match(r'^(sh|sz)\.(60|68|00|30)\d{4}$')]
            
            # 标准化列名
            df = df.rename(columns={
                'code': 'code_bs',
                'code_name': 'name',
            })
            
            # 提取纯代码
            df['code'] = df['code_bs'].str.split('.').str[1]
            
            # BaoStock 不提供实时市值、成交额等数据，设置为默认值
            df['market_cap'] = None
            df['circulating_market_cap'] = None
            df['amount'] = None
            df['turnover_rate'] = None
            df['pe_ratio'] = None
            df['latest_price'] = None
            df['pct_change'] = None
            
            # 获取行业分类
            industry_map = cls._get_industry_map()
            df['industry'] = df['code'].map(industry_map).fillna('未知')
            
            return df
            
        except Exception as e:
            logger.error(f"BaoStock 获取全 A 股数据异常: {e}")
            return None
    
    @classmethod
    def _fetch_from_akshare(cls) -> Optional[pd.DataFrame]:
        """通过 AkShare 获取全 A 股数据（备选）"""
        try:
            import akshare as ak
            
            # 获取实时行情数据（含市值、成交额）
            df_spot = ak.stock_zh_a_spot_em()
            
            if df_spot is None or df_spot.empty:
                return None
            
            # 标准化列名
            column_mapping = {
                '代码': 'code',
                '名称': 'name',
                '总市值': 'market_cap',
                '流通市值': 'circulating_market_cap',
                '成交额': 'amount',
                '换手率': 'turnover_rate',
                '市盈率-动态': 'pe_ratio',
                '最新价': 'latest_price',
                '涨跌幅': 'pct_change',
            }
            
            df_spot = df_spot.rename(columns=column_mapping)
            
            # 过滤：仅保留主板/创业板/科创板/北交所
            df_spot = df_spot[df_spot['code'].str.match(r'^(60|68|00|30|43|83|87)\d{4}$')]
            
            # 显式转换为数值类型，防止过滤时抛出类型异常
            numeric_cols = ['market_cap', 'circulating_market_cap', 'amount', 'turnover_rate', 'pe_ratio', 'latest_price', 'pct_change']
            for col in numeric_cols:
                if col in df_spot.columns:
                    df_spot[col] = pd.to_numeric(df_spot[col], errors='coerce')
            
            # 获取行业分类
            industry_map = cls._get_industry_map()
            df_spot['industry'] = df_spot['code'].map(industry_map).fillna('未知')
            
            # 转换为 A 股统一格式（sh.600519, bj.836149）
            df_spot['code_bs'] = df_spot['code'].apply(
                lambda x: f"sh.{x}" if x.startswith(('60', '68')) else (
                    f"bj.{x}" if x.startswith(('43', '83', '87')) else f"sz.{x}"
                )
            )
            
            return df_spot
            
        except Exception as e:
            logger.error(f"AkShare 获取全 A 股数据异常: {e}")
            return None
    
    @staticmethod
    def _get_industry_map() -> Dict[str, str]:
        """通过 baostock 获取行业分类映射"""
        industry_map = {}
        try:
            import baostock as bs

            lg = bs.login()
            if lg.error_code == '0':
                rs = bs.query_stock_industry()
                while (rs.error_code == '0') & rs.next():
                    row = rs.get_row_data()
                    if row[1] and row[3]:  # code, industry
                        # 提取纯代码（sh.600519 -> 600519）
                        code = row[1].split('.')[1] if '.' in row[1] else row[1]
                        # 提取行业名称（去掉前缀编码）
                        industry = row[3]
                        if industry.startswith(('J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S')):
                            industry = industry[1:]  # 去掉字母前缀
                        industry_map[code] = industry
                bs.logout()
        except Exception as e:
            logger.warning(f"获取行业分类失败: {e}")
        
        return industry_map
    
    @classmethod
    def filter_stocks(
        cls,
        min_market_cap: float = 10e8,      # 最小市值 10 亿
        min_daily_amount: float = 1e8,      # 最小日成交额 1 亿
        exclude_st: bool = True,            # 排除 ST
        industries: List[str] = None,       # 指定行业
    ) -> List[str]:
        """
        过滤股票，返回符合条件的代码列表
        
        Args:
            min_market_cap: 最小总市值（元），默认 10 亿
            min_daily_amount: 最小日成交额（元），默认 1 亿
            exclude_st: 是否排除 ST
            industries: 指定行业列表，None 表示不限
        
        Returns:
            符合条件的股票代码列表（baostock 格式，如 "sh.600519"）
        """
        df = cls.get_all_a_shares_with_info()
        
        # 市值过滤
        if min_market_cap:
            df = df[df['market_cap'] >= min_market_cap]
        
        # 成交额过滤
        if min_daily_amount:
            df = df[df['amount'] >= min_daily_amount]
        
        # ST 过滤
        if exclude_st:
            df = df[~df['name'].str.contains('ST', na=False)]
        
        # 行业过滤
        if industries:
            df = df[df['industry'].isin(industries)]
        
        return df['code_bs'].tolist()
    
    @classmethod
    def get_stock_info(cls, code_bs: str) -> Optional[Dict]:
        """
        获取单只股票的基础信息
        
        Args:
            code_bs: baostock 格式的股票代码（如 "sh.600519"）
        
        Returns:
            股票信息字典，未找到返回 None
        """
        df = cls.get_all_a_shares_with_info()
        
        # 转换为纯代码
        code = code_bs.split('.')[1] if '.' in code_bs else code_bs
        
        row = df[df['code'] == code]
        if row.empty:
            return None
        
        return row.iloc[0].to_dict()
