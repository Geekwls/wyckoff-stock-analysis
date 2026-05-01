# 威科夫分析 Skill - 多平台使用指南

本指南帮助你将威科夫分析skill应用到多个AI平台和场景。

---

## 📚 目录

1. [Claude Code 自动集成](#1-claude-code-自动集成)
2. [其他 AI Agent 兼容指南](#2-其他-ai-agent-兼容指南)
3. [分享与发布](#3-分享与发布)
4. [本地代码嵌入](#4-本地代码嵌入)
5. [常见问题排查](#5-常见问题排查)

---

## 1. Claude Code 自动集成

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

## 2. 其他 AI Agent 兼容指南

由于项目已经抽象为“System Prompt + JSON 输出工具”的标准化架构，它可以完美兼容各类现代 AI 平台。

### 💻 本地代码编辑器 Agent (Cursor / Windsurf 等)

- **使用方法**：在聊天框或 Composer 中 `@` 引用根目录的 `SKILL.md`，并提问：“请帮我用威科夫理论分析 AAPL”。
- **背后原理**：Agent 会读取 `SKILL.md` 的规则，自动在终端运行 `python tools/wyckoff_analyzer.py AAPL --json`，然后将其输出转化为结构化的研报。

### 🤖 ChatGPT Plus / Claude.ai Web端

- **使用方法**：
  1. 将 `SKILL.md` 的内容设为 Custom Instructions (自定义指令) 或 Project Instructions。
  2. 如果您需要量化数据，可以将 `tools/wyckoff_analyzer.py` 以及需要的股票历史数据（CSV）上传给大模型。
- **背后原理**：利用大模型自带的代码解释器 (Code Interpreter / Advanced Data Analysis) 运行脚本，精准输出分析结论。

### 🔌 MCP 兼容平台 (Claude Desktop 等)

- **进阶玩法**：`tools/wyckoff_analyzer.py` 已经支持标准 CLI 传参和 JSON 响应。您可以非常轻松地编写少量代码，将其封装为 **MCP (Model Context Protocol)** Server。
- **效果**：封装后，Claude 桌面版会原生地调用一个叫作 `analyze_stock_wyckoff` 的内建工具，实现无缝衔接。

### ⚙️ Dify / FastGPT 等工作流引擎

- **使用方法**：将 `SKILL.md` 作为主节点的 System Prompt，将 `tools/wyckoff_analyzer.py` 挂载为自定义工具（Custom Tool）节点。
- **效果**：您可以零代码编排搭建出一个对外的“威科夫股票智能诊断机器人”。

---

## 3. 分享与发布

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

#### 方式3：发布到 Claude Plugin Marketplace
1. 将skill包装为Claude插件
2. 提交到官方marketplace
3. 其他人可以一键安装

---

## 4. 本地代码嵌入

### 💻 Python 集成示例

#### Python 调用入口

```python
from tools.wyckoff_analyzer import WyckoffAnalyzer

# 初始化分析器
analyzer = WyckoffAnalyzer("AAPL")

# 生成分析报告
print(analyzer.generate_report())
```

```python
from tools.wyckoff_utils import WyckoffScreener

# 批量筛选
screener = WyckoffScreener()
screener.add_stock("AAPL")
screener.add_stock("TSLA")
print(screener.generate_screening_report())
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
| Web端大模型 | Custom Instructions | 见第2节 |
| 命令行分析 | Python工具 | `tools/wyckoff_analyzer.py` |
| 批量筛选 | 筛选器 | `tools/wyckoff_utils.py` |
| Web界面 | Streamlit应用 | `app/streamlit_app.py` |
| 分享给他人 | GitHub仓库 | 整个目录 |
| 企业应用 | Docker容器 | `docker/` |

---

## 5. 常见问题排查

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

### 大模型回答不准确或出现幻觉？

1. 确保大模型成功执行了 `python tools/wyckoff_analyzer.py --json` 命令。
2. 检查股票代码是否正确（例如 A 股加上 .SH 或 .SZ 后缀）。
3. 如果模型处于离线或无代码执行环境，请手动提供包含成交量的股票历史 CSV 数据。
4. 在提问时强调：“请必须结合量价分析（Effort vs Result）进行判断”。



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
