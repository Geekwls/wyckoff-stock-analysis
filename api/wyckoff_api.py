#!/usr/bin/env python3
"""
威科夫理论股票分析 API
支持多种AI提供商：OpenAI、Anthropic、本地模型
"""

import os
import sys
import json
import argparse
from typing import Optional, Dict, Any
import yfinance as yf
import baostock as bs
import pandas as pd


class WyckoffAnalyzer:
    """威科夫理论分析器"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "openai",
        model: str = "gpt-4"
    ):
        """
        初始化分析器

        Args:
            api_key: API密钥（如果不提供，会从环境变量读取）
            provider: AI提供商（openai/anthropic/ollama）
            model: 模型名称
        """
        self.provider = provider
        self.model = model

        if provider == "openai":
            from openai import OpenAI
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise ValueError("请提供OPENAI_API_KEY环境变量或api_key参数")
            self.client = OpenAI(api_key=self.api_key)

        elif provider == "anthropic":
            import anthropic
            self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            if not self.api_key:
                raise ValueError("请提供ANTHROPIC_API_KEY环境变量或api_key参数")
            self.client = anthropic.Anthropic(api_key=self.api_key)

        elif provider == "ollama":
            # 本地模型，不需要API密钥
            self.client = None
            self.model = model or "llama2"
        
        # 缓存文件路径
        self.cache_file = os.path.join(os.path.dirname(__file__), "stock_cache.json")
        
        # 指数映射表
        self.index_mapping = {
            '上证指数': 'sh.000001',
            '深证成指': 'sz.399001',
            '创业板指': 'sz.399006',
            '沪深300': 'sh.000300',
            '上证50': 'sh.000016',
            '中证500': 'sh.000905',
        }

    def _is_a_stock(self, symbol: str) -> bool:
        """判断是否为A股"""
        # 纯数字 = A股（如 600519）
        # 带 .SH/.SZ = A股（如 600519.SH）
        if symbol.isdigit():
            return True
        if symbol.endswith(('.SH', '.SZ')):
            return True
        return False

    def _is_index(self, symbol: str) -> bool:
        """判断是否为指数"""
        # 中文名称检查
        if symbol in self.index_mapping:
            return True
        # 代码格式检查：sh.000001 或 sz.399001
        if symbol.startswith(('sh.', 'sz.')) and symbol[3:].startswith('0'):
            return True
        return False

    def _resolve_stock_name(self, name: str) -> str:
        """中文名称 → 股票代码"""
        # 1. 查本地缓存
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                
                # 检查缓存是否存在且未过期（30天）
                if name in cache:
                    entry = cache[name]
                    if isinstance(entry, dict):
                        # 新格式：{code, timestamp}
                        import time
                        if time.time() - entry.get('timestamp', 0) < 30 * 24 * 3600:
                            return entry['code']
                    else:
                        # 旧格式：直接是代码
                        return entry
            except Exception:
                pass
        
        # 2. baostock 实时查询
        code = self._search_from_baostock(name)
        
        if code:
            self._update_cache(name, code)
            return code
        
        return None

    def _search_from_baostock(self, keyword: str) -> str:
        """从 baostock 搜索股票"""
        try:
            lg = bs.login()
            if lg.error_code != '0':
                return None
            
            rs = bs.query_stock_basic()
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if data_list:
                df = pd.DataFrame(data_list, columns=rs.fields)
                # 在 code_name 字段中搜索
                match = df[df['code_name'].str.contains(keyword, na=False)]
                if not match.empty:
                    # 返回第一个匹配的代码
                    return match.iloc[0]['code']
        except Exception as e:
            print(f"baostock 查询失败: {e}")
            return None
        
        return None

    def _update_cache(self, name: str, code: str):
        """更新本地缓存"""
        import time
        
        cache = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            except Exception:
                pass
        
        # 新格式：包含时间戳
        cache[name] = {
            'code': code,
            'timestamp': time.time()
        }
        
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"更新缓存失败: {e}")

    def _get_a_stock_data(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """baostock 获取A股数据"""
        try:
            # 转换代码格式：600519 或 600519.SH → sh.600519
            if '.' in symbol:
                parts = symbol.split('.')
                code = f"{parts[1].lower()}.{parts[0]}"
            else:
                prefix = 'sh' if symbol.startswith('6') else 'sz'
                code = f"{prefix}.{symbol}"
            
            # 计算日期范围
            end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
            if period == "1y":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
            elif period == "6mo":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
            elif period == "3mo":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
            else:
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            
            # 登录获取数据
            lg = bs.login()
            if lg.error_code != '0':
                return {"error": f"baostock 登录失败: {lg.error_msg}"}
            
            rs = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"  # 不复权
            )
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if not data_list:
                return {"error": f"无法获取股票 {symbol} 的数据"}
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            df = df.astype({
                'open': float, 'high': float, 'low': float,
                'close': float, 'volume': float, 'amount': float
            })
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
            
            return {
                "symbol": symbol,
                "current_price": latest['close'],
                "high": latest['high'],
                "low": latest['low'],
                "volume": latest['volume'],
                "change": latest['close'] - prev['close'],
                "change_percent": latest['pctChg'],
                "52_week_high": df['high'].max(),
                "52_week_low": df['low'].min(),
                "market_cap": "N/A",  # baostock 不提供市值
                "volume_avg": df['volume'].mean(),
                "history": df.tail(30).to_dict()
            }
            
        except Exception as e:
            return {"error": f"获取A股数据时出错: {str(e)}"}

    def _get_global_stock_data(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """yfinance 获取其他市场数据"""
        try:
            stock = yf.Ticker(symbol)
            hist = stock.history(period=period)
            
            if hist.empty:
                return {"error": f"无法获取股票 {symbol} 的数据"}
            
            latest = hist.iloc[-1]
            info = stock.info
            
            return {
                "symbol": symbol,
                "current_price": latest['Close'],
                "high": latest['High'],
                "low": latest['Low'],
                "volume": latest['Volume'],
                "change": latest['Close'] - hist['Close'].iloc[-2] if len(hist) > 1 else 0,
                "change_percent": ((latest['Close'] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2] * 100) if len(hist) > 1 else 0,
                "52_week_high": info.get('fiftyTwoWeekHigh', 'N/A'),
                "52_week_low": info.get('fiftyTwoWeekLow', 'N/A'),
                "market_cap": info.get('marketCap', 'N/A'),
                "volume_avg": info.get('averageVolume', 'N/A'),
                "history": hist.tail(30).to_dict()
            }
        except Exception as e:
            return {"error": f"获取数据时出错: {str(e)}"}

    def _get_index_data(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """获取指数数据"""
        try:
            # 转换中文名称为代码
            if symbol in self.index_mapping:
                code = self.index_mapping[symbol]
            else:
                code = symbol
            
            # 计算日期范围
            end_date = pd.Timestamp.now().strftime('%Y-%m-%d')
            if period == "1y":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
            elif period == "6mo":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=180)).strftime('%Y-%m-%d')
            elif period == "3mo":
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
            else:
                start_date = (pd.Timestamp.now() - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
            
            # 登录获取数据
            lg = bs.login()
            if lg.error_code != '0':
                return {"error": f"baostock 登录失败: {lg.error_msg}"}
            
            rs = bs.query_history_k_data_plus(
                code,
                "date,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d"
            )
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if not data_list:
                return {"error": f"无法获取指数 {symbol} 的数据"}
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            df = df.astype({
                'open': float, 'high': float, 'low': float,
                'close': float, 'volume': float, 'amount': float
            })
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else df.iloc[-1]
            
            return {
                "symbol": symbol,
                "current_price": latest['close'],
                "high": latest['high'],
                "low": latest['low'],
                "volume": latest['volume'],
                "change": latest['close'] - prev['close'],
                "change_percent": ((latest['close'] - prev['close']) / prev['close'] * 100) if prev['close'] > 0 else 0,
                "52_week_high": df['high'].max(),
                "52_week_low": df['low'].min(),
                "market_cap": "N/A",
                "volume_avg": df['volume'].mean(),
                "history": df.tail(30).to_dict()
            }
            
        except Exception as e:
            return {"error": f"获取指数数据时出错: {str(e)}"}

    def get_stock_data(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """
        获取股票数据（自动识别市场）

        Args:
            symbol: 股票代码或中文名称
                - A股代码: "600519", "600519.SH"
                - A股名称: "贵州茅台", "比亚迪"
                - 指数: "上证指数", "深证成指", "沪深300"
                - 美股: "AAPL", "NVDA"
                - 港股: "0700.HK"
            period: 时间周期（1y, 6mo, 3mo, 1mo）

        Returns:
            包含股票数据的字典
        """
        # 1. 检查是否为指数
        if self._is_index(symbol):
            return self._get_index_data(symbol, period)
        
        # 2. 中文名称解析为代码
        if not symbol.replace('.', '').isdigit() and not symbol.isalpha():
            resolved = self._resolve_stock_name(symbol)
            if resolved:
                symbol = resolved
            else:
                return {"error": f"无法识别股票名称: {symbol}"}
        
        # 3. 判断市场并获取数据
        if self._is_a_stock(symbol):
            return self._get_a_stock_data(symbol, period)
        else:
            return self._get_global_stock_data(symbol, period)

    def load_system_prompt(self) -> str:
        """加载威科夫理论系统提示词"""
        prompt_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "prompts",
            "wyckoff-system-prompt.md"
        )

        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 提取代码块中的内容
                if "```system" in content:
                    start = content.find("```system") + 9
                    end = content.find("```", start)
                    return content[start:end].strip()
                return content
        except FileNotFoundError:
            # 如果文件不存在，使用内置的精简版
            return """You are a Wyckoff technical analyst. Analyze stocks using:
1. Law of Supply & Demand
2. Law of Cause & Effect
3. Law of Effort vs Result

Identify: Accumulation, Markup, Distribution, Markdown phases.
Key events: PS, CL, AR, ST, Spring, Upthrust, SOS, SOW, LPS, LPSY.
Always include disclaimers."""

    def analyze(
        self,
        symbol: str,
        include_data: bool = True,
        custom_prompt: Optional[str] = None
    ) -> str:
        """
        使用AI分析股票

        Args:
            symbol: 股票代码
            include_data: 是否包含股票数据
            custom_prompt: 自定义提示词

        Returns:
            AI生成的分析文本
        """
        system_prompt = self.load_system_prompt()

        # 构建用户消息
        if include_data:
            stock_data = self.get_stock_data(symbol)
            if "error" in stock_data:
                user_message = f"请分析股票 {symbol}。错误: {stock_data['error']}"
            else:
                user_message = f"""请使用威科夫理论分析以下股票：

**股票代码**: {symbol}
**当前价格**: {stock_data['current_price']:.2f}
**今日涨跌幅**: {stock_data['change_percent']:.2f}%
**成交量**: {stock_data['volume']:,.0f}
**今日最高**: {stock_data['high']:.2f}
**今日最低**: {stock_data['low']:.2f}
**52周最高**: {stock_data['52_week_high']}
**52周最低**: {stock_data['52_week_low']}
**市值**: {stock_data['market_cap']:, if isinstance(stock_data['market_cap'], (int, float)) else stock_data['market_cap']}

请按照威科夫分析框架提供完整分析。"""
        else:
            user_message = f"请使用威科夫理论分析股票 {symbol}"

        if custom_prompt:
            user_message = custom_prompt

        # 调用不同的AI提供商
        try:
            if self.provider == "openai":
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7
                )
                return response.choices[0].message.content

            elif self.provider == "anthropic":
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_message}
                    ]
                )
                return response.content[0].text

            elif self.provider == "ollama":
                import requests
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": self.model,
                        "prompt": f"System: {system_prompt}\n\nUser: {user_message}",
                        "stream": False
                    }
                )
                return response.json().get("response", "无法获取响应")

        except Exception as e:
            return f"分析时出错: {str(e)}"


def main():
    """命令行接口"""
    parser = argparse.ArgumentParser(description="威科夫理论股票分析工具")
    parser.add_argument("symbol", help="股票代码（如 AAPL, 002575.SZ）")
    parser.add_argument("--provider", choices=["openai", "anthropic", "ollama"],
                       default="openai", help="AI提供商")
    parser.add_argument("--model", help="模型名称（如 gpt-4, claude-3-sonnet）")
    parser.add_argument("--no-data", action="store_true",
                       help="不包含股票数据（AI将自行搜索）")
    parser.add_argument("--output", "-o", help="输出到文件")

    args = parser.parse_args()

    # 创建分析器
    try:
        analyzer = WyckoffAnalyzer(provider=args.provider, model=args.model)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    # 执行分析
    print(f"正在使用 {args.provider} 分析 {args.symbol}...")
    result = analyzer.analyze(args.symbol, include_data=not args.no_data)

    # 输出结果
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"分析结果已保存到 {args.output}")
    else:
        print("\n" + "="*60)
        print(result)
        print("="*60)


if __name__ == "__main__":
    main()
