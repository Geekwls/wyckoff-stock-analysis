# Wyckoff Stock Analysis Skill v3.3.0

> 一个专为 AI Agent（如 Claude Code, Cursor, MCP 客户端）打造的威科夫股票分析标准组件。

基于理查德·威科夫（Richard D. Wyckoff）的经典量价理论，本项目提供了一套**“提示词路由 + 本地量化工具”**的双核架构，使大语言模型能够 100% 准确地获取股票形态数据，并进行深度的市场周期分析。

---

## 🌟 核心特性 (v3.3.0 架构)

本项目已经超越了单纯的“提示词模板”，进化为一个平台无关的 Agent 技能包：

1. **双核驱动**：
   - **大脑**：精简高效的 `SKILL.md`（充当 System Prompt Router）。
   - **四肢**：`tools/wyckoff_analyzer.py`（Python 数据获取与形态检测引擎）。
2. **AI 友好输出**：核心分析器提供 `--json` 参数，输出结构化数据（含阶段识别、支撑压力位、因果目标价等），彻底消除大模型解析纯文本时产生的幻觉。
3. **全平台兼容**：完美支持 Cursor、Windsurf、Claude Code、ChatGPT Plus、Dify 等各类现代 AI 工作流生态。
4. **内置 A 股适配**：特殊的规则约束，防止 AI 误判 A 股“一字涨跌停”等极端量价形态。

---

## 🚀 快速上手

### 1. 安装依赖环境

建议在 Python 3.8+ 环境下运行：

```bash
git clone https://github.com/Geekwls/wyckoff-stock-analysis.git
cd wyckoff-stock-analysis
pip install -r requirements.txt
```

### 2. 命令行快速测试 (人类视角)

直接在终端运行分析器，获取格式化的分析报告：

```bash
# 分析美股
python tools/wyckoff_analyzer.py AAPL

# 分析 A 股 (需要 baostock 数据)
python tools/wyckoff_analyzer.py sh.600519
```

### 3. JSON 数据接口 (AI 视角)

使用 `--json` 参数，获取供 AI Agent 解析的结构化数据：

```bash
python tools/wyckoff_analyzer.py AAPL --json
```

---

## 🤖 AI 平台集成指南

想让你的 AI 变成威科夫专家？集成方法非常简单。

详细教程请参考：👉 **[HOW_TO_USE.md (多平台使用指南)](HOW_TO_USE.md)**

**简要说明：**
- **本地 Agent (Cursor / Claude Code)**：无需配置。直接在其终端中提问，或 `@SKILL.md` 即可。Agent 会自动调用 Python 脚本。
- **Web 端大模型 (ChatGPT / Claude)**：将 `SKILL.md` 内容设为 Custom Instructions，并允许模型使用 Python 解释器运行 `tools/` 目录下的代码。

---

## 📁 文件结构

```text
wyckoff-stock-analysis/
├── SKILL.md                          # 核心：AI Agent 系统提示词/路由规则
├── README.md                         # 本说明文件
├── HOW_TO_USE.md                     # 多平台 AI 接入使用指南
│
├── requirements.txt                  # Python 环境依赖包
├── tools/                            # 本地量化工具库
│   ├── wyckoff_analyzer.py           # 核心引擎：数据获取、阶段检测、JSON 输出
│   └── wyckoff_utils.py              # 辅助工具：批量筛选、报告生成
│
├── references/                       # 威科夫理论知识库 (供 AI 检索 RAG)
│   ├── wyckoff-theory-full.md        # 完整理论与量化标准
│   ├── china-market-guide.md         # A股市场特色指南
│   ├── common-pitfalls.md            # 实战常见错误与避坑
│   ├── learning-path.md              # 学习路线图
│   └── chart-examples/               # 实战图表案例库 (30+ 案例)
│
├── app/                              # Web 独立应用
│   └── streamlit_app.py              # 可视化界面面板
│
└── examples/                         # 调用示例
    └── example_usage.py              # Python API 使用案例
```

---

## 📚 威科夫理论学习资源

如果你是人类交易员，希望系统学习威科夫理论（Wyckoff Method），项目中也包含了极其丰富的学习资料：

- 📖 **理论核心**：[威科夫理论全解析](references/wyckoff-theory-full.md)（含四大阶段、九大事件、三大定律）
- 🛤️ **学习路线**：[渐进式学习指南](references/learning-path.md)
- ⚠️ **实战避坑**：[常见错误与陷阱](references/common-pitfalls.md)
- 🇨🇳 **A 股专区**：[中国市场特色指南](references/china-market-guide.md)

*注：威科夫理论是概率游戏，不保证 100% 盈利，请严格做好仓位管理与止损。*

---

## 🔄 更新日志

### v3.3.0 (2026-05-01) - 情绪风控与多时间框架引擎
- ✨ **全局情绪预警**：动态拉取 VIX/VHSI 或大盘历史实现波动率，自动计算 A股/港股/美股恐慌指数。
- ✨ **仓位动态风控**：根据情绪指数自动缩放建议仓位（恐慌减仓，贪婪加仓），并在“贪婪+派发”时触发背离极其危险预警。
- ✨ **多维度降维打击**：引入周线、月线长期趋势判定，并增加与大盘的相对强度 (Relative Strength) 量化分析。

### v3.2.0 (2026-05-01) - V2 威科夫事件推演引擎
- ✨ **事件驱动阶段识别**：废弃纯均线判断，底层改为通过严谨探测（高潮 CL -> 自动反抽 AR -> 震仓 Spring）事件因果链来倒推威科夫阶段。
- ✨ **动态历史回测**：加入基于当前个股自身历史数据的形态表现回测引擎，动态计算每次 SOS/SOW/Spring 的真实历史专属胜率。
- ✨ **术语大白话解析**：根据当前所处阶段及爆发的信号，自动输出动态的“术语百科”，供大模型快速渲染。

### v3.1.0 (2026-05-01) - AI Agent 架构重构
- ✨ **架构升级**：完全重构为“System Prompt + JSON 工具”的现代化 Agent 技能标准架构。
- ✨ **SKILL 瘦身**：剥离长篇理论至独立参考文档，将 `SKILL.md` 优化为极度精简的 Agent 路由规则。
- ✨ **JSON 机器可读接口**：核心分析器新增 `--json` 格式化输出，保障大模型 100% 稳定解析返回数据。
- 🧹 **依赖与文件清理**：废弃冗余的 `api/` 目录和旧脚本，在根目录提供统一的 `requirements.txt`。
- 📚 **多平台兼容**：全面重写 `HOW_TO_USE.md`，新增 Cursor、Dify、MCP 等最新 AI 工作流的集成方案。

### v3.0 (2026-04-30) - 专家级版本
- ✨ 新增30+实战图表案例与失败形态案例分析
- ✨ 新增威科夫形态自动识别 Python 工具
- ✨ 新增 A 股市场特定指南与批量股票筛选器

### v2.0 & v1.0
- 完成基础威科夫理论、阶段分析体系搭建，支持基础 Prompt 模板。

---

## 🤝 贡献与反馈

如果你对量化逻辑有改进建议、发现了 bug，或者想分享绝佳的交易案例，欢迎提交 Issue 或 Pull Request！

**祝你交易成功！记住：保护本金永远是第一要务。** 📈
