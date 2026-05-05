# 威科夫分析 Skill - 多平台使用指南

> 版本：v1.0.0 | 最后更新：2026-05-05

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

### ✅ 本地 Agent 直接可用

将项目放在任意目录，Agent 即可通过 `src/wyckoff/facade.py` 进行分析。

**使用方法**：
```
# 直接询问，skill会自动激活
"请用威科夫理论分析 茅台"
"AAPL 处于威科夫周期的哪个阶段？"
"应用威科夫方法分析 比亚迪"
```

---

## 2. 其他 AI Agent 兼容指南

由于项目已经抽象为"System Prompt + JSON 输出工具"的标准化架构，它可以完美兼容各类现代 AI 平台。

### 💻 本地代码编辑器 Agent (Cursor / Windsurf 等)

- **使用方法**：在聊天框或 Composer 中 `@` 引用根目录的 `SKILL.md`，并提问："请帮我用威科夫理论分析 AAPL"。
- **背后原理**：Agent 会读取 `SKILL.md` 的规则，自动在终端运行 `python -m apps.cli.main AAPL --json`，然后将其输出转化为结构化的研报。

### 🤖 ChatGPT Plus / Claude.ai Web端

- **使用方法**：
  1. 将 `SKILL.md` 的内容设为 Custom Instructions (自定义指令) 或 Project Instructions。
  2. 如果需要量化数据，可以将 `src/wyckoff/facade.py` 上传给大模型。
- **背后原理**：利用大模型自带的代码解释器 (Code Interpreter / Advanced Data Analysis) 运行脚本，精准输出分析结论。

### 🔌 MCP 兼容平台 (Claude Desktop / Cursor)

- **进阶玩法**：本项目内置了原生的 MCP Server。你只需要将 `apps/mcp/server.py` 挂载到兼容 MCP 的客户端即可。
- **Claude Desktop 配置示例** (`claude_desktop_config.json`):
  ```json
  {
    "mcpServers": {
      "wyckoff_analyzer": {
        "command": "python",
        "args": ["/绝对路径/到/wyckoff-stock-analysis/apps/mcp/server.py"]
      }
    }
  }
  ```
- **效果**：封装后，客户端会原生地调用 `analyze_stock_wyckoff` 和 `batch_analyze_sector` 工具，实现无缝衔接，且入参出参自带 Schema 验证。

### ⚙️ Dify / FastGPT 等工作流引擎

- **使用方法**：将 `SKILL.md` 作为主节点的 System Prompt，将 `src/wyckoff/facade.py` 挂载为自定义工具（Custom Tool）节点。
- **效果**：您可以零代码编排搭建出一个对外的"威科夫股票智能诊断机器人"。

---

## 3. 分享与发布

### 📤 多种分享方式

#### 方式1：GitHub 仓库
```bash
cd wyckoff-stock-analysis
git init
git add .
git commit -m "Add Wyckoff stock analysis skill"
gh repo create wyckoff-stock-analysis --public
git push -u origin main
```

#### 方式2：导出为ZIP
```bash
zip -r wyckoff-skill.zip wyckoff-stock-analysis/
```

#### 方式3：发布到 Claude Plugin Marketplace
1. 将skill包装为Claude插件
2. 提交到官方marketplace
3. 其他人可以一键安装

---

## 4. 本地代码嵌入

### 💻 Python 集成示例

```python
from src.wyckoff.facade import WyckoffAnalyzer

# 单股分析
analyzer = WyckoffAnalyzer("AAPL")
analyzer.fetch_data()

# 生成专业文本报告
print(analyzer.generate_report())

# 获取强类型 JSON 结果 (Pydantic Model)
json_data = analyzer.generate_json()

# 批量扫描
from src.wyckoff.services.screener_service import ScreenerService
results = ScreenerService().quick_scan(["AAPL", "MSFT", "GOOGL"])
```

---

## 📋 快速参考

### 不同场景的最佳选择

| 使用场景 | 推荐方式 | 文件位置 |
|---------|---------|---------|
| 命令行分析 | Python CLI | `python -m apps.cli.main [SYMBOL]` |
| Python集成 | Facade API | `src/wyckoff/facade.py` |
| MCP接入 | MCP Server | `apps/mcp/server.py` |
| 批量筛选 | ScreenerService | `src/wyckoff/services/screener_service.py` |

---

## 5. 常见问题排查

### Skill在Claude Code中不生效？

1. **检查路径**：
```bash
ls -la SKILL.md
```

2. **检查frontmatter**：
```bash
head -10 SKILL.md
```
应该包含 `---` 包围的元数据

3. **重启Claude Code**

### 大模型回答不准确或出现幻觉？

1. 确保大模型成功执行了 `python -m apps.cli.main [SYMBOL] --json` 命令。
2. 检查股票代码是否正确（例如 A 股加上 .SH 或 .SZ 后缀）。
3. 如果模型处于离线或无代码执行环境，请手动提供包含成交量的股票历史 CSV 数据。
4. 在提问时强调："请必须结合量价分析（Effort vs Result）进行判断"。

### 分析结果中 SOS 信号与派发阶段矛盾？

这是 v1.0.0 已修复的问题。如果仍然出现：
1. 检查是否使用了最新版本
2. 确认 `src/wyckoff/core/detectors/strength_weakness_detector.py` 中的 `detect_sos()` 方法是否包含阶段约束逻辑

### 因果法则目标显示不合理？

v1.0.0 已优化：未跌破支撑前不展示下跌目标，改为"潜在目标（待触发）"状态。

---

## 📞 获取帮助

- 示例: `examples/` 目录
- 理论参考: `references/` 目录

---

## 🔄 持续更新

- 定期更新skill内容
- 添加新的分析案例
- 改进API性能
- 优化prompt模板

---

**祝你使用愉快！** 📈
