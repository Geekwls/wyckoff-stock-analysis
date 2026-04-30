#!/bin/bash
# 威科夫分析命令行使用示例

echo "=========================================="
echo "威科夫理论股票分析 - 命令行示例"
echo "=========================================="
echo ""

# 示例 1: 使用 OpenAI GPT-4 分析苹果股票
echo "示例 1: 分析苹果股票 (AAPL)"
echo "命令: python api/wyckoff_api.py AAPL --provider openai --model gpt-4"
echo ""

# 示例 2: 使用 Anthropic Claude 分析特斯拉
echo "示例 2: 使用 Claude 分析特斯拉 (TSLA)"
echo "命令: python api/wyckoff_api.py TSLA --provider anthropic --model claude-3-sonnet-20240229"
echo ""

# 示例 3: 分析A股（群兴玩具）
echo "示例 3: 分析A股 - 群兴玩具"
echo "命令: python api/wyckoff_api.py 002575.SZ --provider openai"
echo ""

# 示例 4: 保存分析结果到文件
echo "示例 4: 保存分析结果到文件"
echo "命令: python api/wyckoff_api.py NVDA -o nvda_analysis.md"
echo ""

# 示例 5: 使用本地模型（需要先安装 Ollama）
echo "示例 5: 使用本地 Ollama 模型"
echo "命令: python api/wyckoff_api.py AAPL --provider ollama --model llama2"
echo ""

# 示例 6: 不包含股票数据（让AI自行搜索）
echo "示例 6: 让AI自行搜索股票数据"
echo "命令: python api/wyckoff_api.py AAPL --no-data"
echo ""

echo "=========================================="
echo "提示: 确保已安装依赖：pip install -r api/requirements.txt"
echo "提示: 设置环境变量：export OPENAI_API_KEY=your_key"
echo "=========================================="
