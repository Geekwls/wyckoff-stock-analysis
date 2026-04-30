#!/bin/bash
# 威科夫分析 Skill - 快速开始脚本

set -e

echo "=========================================="
echo "威科夫理论股票分析 Skill"
echo "快速开始指南"
echo "=========================================="
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

echo "✅ Python 已安装"
echo ""

# 显示目录结构
echo "📁 Skill 目录结构:"
echo ""
tree ~/.claude/user-skills/wyckoff-stock-analysis/ 2>/dev/null || find ~/.claude/user-skills/wyckoff-stock-analysis/ -type f | head -20
echo ""

# 显示使用方式
echo "=========================================="
echo "🚀 使用方式"
echo "=========================================="
echo ""

echo "1️⃣  在 Claude Code 中使用（已自动配置）"
echo "   直接询问: '请用威科夫理论分析 AAPL'"
echo ""

echo "2️⃣  在 ChatGPT 中使用"
echo "   打开 prompts/wyckoff-quick.md"
echo "   复制内容到 ChatGPT"
echo ""

echo "3️⃣  作为命令行工具"
echo "   安装依赖:"
echo "   pip install -r api/requirements.txt"
echo ""
echo "   设置API密钥:"
echo "   export OPENAI_API_KEY=your_key"
echo ""
echo "   运行分析:"
echo "   python api/wyckoff_api.py AAPL"
echo ""

echo "4️⃣  作为 Web 应用"
echo "   安装依赖:"
echo "   pip install streamlit"
echo ""
echo "   运行应用:"
echo "   streamlit run app/streamlit_app.py"
echo ""

echo "=========================================="
echo "📚 更多信息"
echo "=========================================="
echo ""
echo "详细文档: HOW_TO_USE.md"
echo "示例代码: examples/example_usage.py"
echo "Prompt模板: prompts/"
echo ""

echo "✅ 设置完成！"
echo ""
