#!/usr/bin/env python3
"""
威科夫理论股票分析 Web 应用
使用 Streamlit 构建
"""

import streamlit as st
import os
from dotenv import load_dotenv
import sys

# 添加API目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from wyckoff_api import WyckoffAnalyzer

# 加载环境变量
load_dotenv()

# 页面配置
st.set_page_config(
    page_title="威科夫理论股票分析",
    page_icon="📈",
    layout="wide"
)

# 标题
st.title("📈 威科夫理论股票分析工具")
st.markdown("""
基于理查德·威科夫（Richard D. Wyckoff）的股票技术分析方法。
识别市场周期、积累/分布模式，并提供交易建议。
""")

# 侧边栏配置
st.sidebar.header("⚙️ 设置")

# AI提供商选择
provider = st.sidebar.selectbox(
    "选择 AI 提供商",
    ["openai", "anthropic", "ollama"],
    help="选择用于分析的AI模型提供商"
)

# 模型选择
if provider == "openai":
    model = st.sidebar.selectbox(
        "模型",
        ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
        index=0
    )
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.sidebar.warning("⚠️ 请设置 OPENAI_API_KEY 环境变量")

elif provider == "anthropic":
    model = st.sidebar.selectbox(
        "模型",
        ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
        index=1
    )
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        st.sidebar.warning("⚠️ 请设置 ANTHROPIC_API_KEY 环境变量")

else:
    model = st.sidebar.text_input("模型名称", value="llama2")
    api_key = None
    st.sidebar.info("Ollama 本地模型需要先启动服务")

# 主界面
st.header("📊 股票分析")

col1, col2 = st.columns([2, 1])

with col1:
    symbol = st.text_input(
        "股票代码",
        placeholder="例如: AAPL, TSLA, 002575.SZ",
        help="输入股票代码，美股代码直接输入，A股代码加上.SZ或.SS后缀"
    )

with col2:
    include_data = st.checkbox("包含股票数据", value=True)

# 分析按钮
analyze_button = st.button("🔍 开始分析", type="primary", use_container_width=True)

# 结果显示
if analyze_button:
    if not symbol:
        st.error("❌ 请输入股票代码")
    else:
        try:
            # 创建分析器
            analyzer = WyckoffAnalyzer(
                provider=provider,
                model=model
            )

            # 显示加载状态
            with st.spinner(f"正在使用 {provider} ({model}) 分析 {symbol}..."):
                result = analyzer.analyze(symbol, include_data=include_data)

            # 显示结果
            st.success("✅ 分析完成！")
            st.markdown("---")
            st.markdown(result)

            # 下载按钮
            st.download_button(
                label="📥 下载分析结果",
                data=result,
                file_name=f"{symbol}_wyckoff_analysis.md",
                mime="text/markdown"
            )

        except ValueError as e:
            st.error(f"❌ 配置错误: {str(e)}")
            st.info("💡 请检查侧边栏的API密钥设置")

        except Exception as e:
            st.error(f"❌ 分析失败: {str(e)}")

# 底部信息
st.markdown("---")
st.markdown("""
### 📚 威科夫理论简介

威科夫理论是技术分析的重要方法，由理查德·威科夫（Richard D. Wyckoff）创立，主要包括：

1. **供求定律**：价格由供需不平衡驱动
2. **因果定律**：每个价格变动都有前因
3. **努力vs结果定律**：成交量与价格变动的对比

### ⚠️ 免责声明

本工具提供的分析仅供参考，不构成任何投资建议。
股市有风险，投资需谨慎。请根据自己的风险承受能力做出投资决策。
""")

# 使用说明
with st.expander("📖 使用说明"):
    st.markdown("""
    #### 支持的股票代码格式
    - **美股**: 直接输入代码，如 `AAPL`, `TSLA`, `NVDA`
    - **A股**: 加上后缀，深圳 `002575.SZ`，上海 `600519.SS`
    - **港股**: 加上 `.HK` 后缀，如 `0700.HK`

    #### AI 提供商说明
    - **OpenAI**: 需要 API Key，推荐使用 GPT-4 获得最佳效果
    - **Anthropic**: 需要 API Key，Claude-3 Sonnet 性价比高
    - **Ollama**: 本地运行，无需 API Key，需要先安装 Ollama

    #### 环境变量设置
    在项目目录创建 `.env` 文件：
    ```
    OPENAI_API_KEY=your_key_here
    ANTHROPIC_API_KEY=your_key_here
    ```
    """)
