# 威科夫分析 Skill - 多平台使用指南

本指南帮助你将威科夫分析skill应用到多个AI平台和场景。

---

## 📚 目录

1. [Claude Code 使用（已配置）](#1-claude-code-使用)
2. [导出为 Prompt 模板](#2-导出为-prompt-模板)
3. [集成到 ChatGPT/Claude.ai](#3-集成到-chatgptclaudeai)
4. [创建 API 版本](#4-创建-api-版本)
5. [分享给其他人](#5-分享给其他人)
6. [嵌入到应用中](#6-嵌入到应用中)

---

## 1. Claude Code 使用

### ✅ 已自动激活

你的skill已经放在正确位置 `~/.claude/user-skills/wyckoff-stock-analysis/`

**使用方法**：
```
# 直接询问，skill会自动激活
"请用威科夫理论分析 茅台"
"AAPL 处于威科夫周期的哪个阶段？"
"应用威科夫方法分析 比亚迪"
```

**验证skill是否加载**：
```bash
ls -la ~/.claude/user-skills/wyckoff-stock-analysis/
```

---

## 2. 导出为 Prompt 模板

### 📝 创建通用版本

已为你创建了 `prompts/` 目录，包含多个版本：

1. **wyckoff-full.md** - 完整版（适合深度分析）
2. **wyckoff-quick.md** - 快速版（适合快速查询）
3. **wyckoff-system-prompt.md** - AI系统提示词版

**使用方法**：

#### 在 ChatGPT 中使用：
1. 打开 [ChatGPT](https://chat.openai.com)
2. 创建新对话
3. 复制 `prompts/wyckoff-full.md` 内容
4. 粘贴到输入框
5. 发送后开始提问

#### 在 Claude.ai 中使用：
1. 打开 [Claude.ai](https://claude.ai)
2. 创建新对话
3. 在自定义指令中使用 `prompts/wyckoff-system-prompt.md`
4. 保存后所有对话都会应用威科夫理论

#### 在其他AI平台使用：
- 文心一言、通义千问、DeepSeek等
- 直接复制粘贴prompt即可使用

---

## 3. 集成到 ChatGPT/Claude.ai

### 🤖 ChatGPT Custom Instructions

1. 访问 [ChatGPT 设置](https://chat.openai.com/settings)
2. 点击 "Custom instructions"
3. 在 "How would you like ChatGPT to respond?" 中添加：
```
When analyzing stocks or answering questions about technical analysis, apply the Wyckoff Method framework:

1. Use the three fundamental laws: Supply & Demand, Cause & Effect, Effort vs Result
2. Identify market cycle phases: Accumulation, Markup, Distribution, Markdown
3. Locate key Wyckoff events: PS, CL, AR, ST, Spring/Upthrust, SOS/SOW, LPS/LPSY
4. Analyze volume-price relationships
5. Project targets using Cause & Effect law
6. Always include risk warnings and disclaimers

For detailed guidance, refer to the Wyckoff analysis framework.
```

### 🎨 Claude.ai Custom Instructions

1. 访问 [Claude.ai](https://claude.ai)
2. 创建账号并登录
3. 点击 "Customize" 或 "Custom Instructions"
4. 添加相同的内容

---

## 4. 创建 API 版本

### 🔌 使用 OpenAI/Claude API

已为你创建了 API wrapper：`api/wyckoff-api.py`

**安装依赖**：
```bash
pip install openai anthropic requests yfinance
```

**使用示例**：
```bash
# 作为命令行工具
python api/wyckoff-api.py "AAPL" --model gpt-4

# 或作为Python模块
from api.wyckoff_api import WyckoffAnalyzer
analyzer = WyckoffAnalyzer()
result = analyzer.analyze("AAPL", provider="openai")
print(result)
```

**API支持**：
- OpenAI GPT-4/GPT-3.5
- Anthropic Claude
- 本地模型（通过 Ollama）

---

## 5. 分享给其他人

### 📤 多种分享方式

#### 方式1：GitHub 仓库
```bash
cd ~/.claude/user-skills/wyckoff-stock-analysis
git init
git add .
git commit -m "Add Wyckoff stock analysis skill"
gh repo create wyckoff-stock-analysis --public
git push -u origin main
```

#### 方式2：导出为ZIP
```bash
cd ~/.claude/user-skills
zip -r wyckoff-skill.zip wyckoff-stock-analysis/
```

#### 方式3：分享 Prompt 模板
直接分享 `prompts/` 目录中的 `.md` 文件

#### 方式4：发布到 Claude Plugin Marketplace
1. 将skill包装为Claude插件
2. 提交到官方marketplace
3. 其他人可以一键安装

---

## 6. 嵌入到应用中

### 💻 Python 集成示例

```python
from api.wyckoff_api import WyckoffAnalyzer

# 初始化分析器
analyzer = WyckoffAnalyzer(api_key="your-api-key")

# 分析股票
result = analyzer.analyze_stock(
    symbol="AAPL",
    provider="openai",  # 或 "anthropic", "ollama"
    include_charts=True
)

# 获取分析结果
print(result['phase'])          # 当前阶段
print(result['analysis'])       # 完整分析
print(result['recommendation']) # 交易建议
```

### 🌐 Web 应用

已提供简单的 Streamlit 应用：`app/streamlit_app.py`

**运行**：
```bash
pip install streamlit yfinance
streamlit run app/streamlit_app.py
```

**访问**：http://localhost:8501

---

## 📋 快速参考

### 不同场景的最佳选择

| 使用场景 | 推荐方式 | 文件位置 |
|---------|---------|---------|
| Claude Code本地使用 | 已自动激活 | `~/.claude/user-skills/` |
| ChatGPT一次性使用 | 复制粘贴prompt | `prompts/wyckoff-quick.md` |
| ChatGPT永久使用 | Custom Instructions | 见第3节 |
| 批量分析 | Python API | `api/wyckoff-api.py` |
| Web界面 | Streamlit应用 | `app/streamlit_app.py` |
| 分享给他人 | GitHub仓库 | 整个目录 |
| 企业应用 | Docker容器 | `docker/` |

---

## 🛠️ 故障排查

### Skill在Claude Code中不生效？

1. **检查路径**：
```bash
ls -la ~/.claude/user-skills/wyckoff-stock-analysis/SKILL.md
```

2. **检查frontmatter**：
```bash
head -10 ~/.claude/user-skills/wyckoff-stock-analysis/SKILL.md
```
应该包含 `---` 包围的元数据

3. **重启Claude Code**

### ChatGPT回答不准确？

1. 使用完整的 `wyckoff-full.md` 版本
2. 附加具体的股票数据
3. 要求分步分析：
```
"请按照以下步骤分析：
1. 识别当前阶段
2. 定位关键事件
3. 分析成交量
4. 给出交易建议"
```

### API调用失败？

1. 检查API密钥：`export OPENAI_API_KEY=xxx`
2. 查看错误日志
3. 确认网络连接

---

## 📞 获取帮助

- GitHub Issues: [创建issue](https://github.com/your-repo/issues)
- 文档: `docs/` 目录
- 示例: `examples/` 目录

---

## 🔄 持续更新

- 定期更新skill内容
- 添加新的分析案例
- 改进API性能
- 优化prompt模板

---

**祝你使用愉快！** 📈
