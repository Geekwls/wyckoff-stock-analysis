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

    def get_stock_data(self, symbol: str, period: str = "1y") -> Dict[str, Any]:
        """
        获取股票数据

        Args:
            symbol: 股票代码（如 "AAPL", "002575.SZ"）
            period: 时间周期（1y, 6mo, 3mo, 1mo）

        Returns:
            包含股票数据的字典
        """
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
                "history": hist.tail(30).to_dict()  # 最近30天数据
            }
        except Exception as e:
            return {"error": f"获取数据时出错: {str(e)}"}

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
