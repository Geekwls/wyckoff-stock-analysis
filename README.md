#  Wyckoff Stock Analysis Skill v2.0.0

> **专业级 AI Agent 威科夫量化分析组件**
> 专为 Claude Code, Cursor, MCP 客户端及量化交易员打造的"大脑+工具"双核引擎。
 
---

## 💎 为什么选择本项目？

本项目并非简单的"提示词模板"，而是一套经过生产级重构的 **Agent 技能包**。
1.  **零幻觉**：形态识别由本地 Python 向量化算法完成，模型仅负责逻辑推理。
2.  **全量化**：基于理查德·威科夫（Richard D. Wyckoff）的经典理论，将抽象概念转为精确的数学阈值。
3.  **动态术��**：根据当前市场阶段（吸筹/派发）动态调整术语解释，确保分析结论一致。
4.  **逻辑证伪**：明确列出"什么情况下你判断错了"，提供可执行、可纠错的交易系统预案。

---

## 🏗️ 核心架构：大脑与四肢

```mermaid
graph TD
    A[AI Agent / Human] -->|调用| B(SKILL.md - 决策大脑)
    B -->|调度| C{src/wyckoff/facade.py - 统一入口}
    C -->|数据获取| D[src/wyckoff/core/data_fetcher.py]
    C -->|形态探测| E[src/wyckoff/core/pattern_detector.py]
    C -->|规律分析| F[src/wyckoff/core/law_analyzer.py]
    C -->|报告生成| G[src/wyckoff/core/report_generator.py]
    D -.->|A股/港股| H[Baostock/YFinance]
    G -->|输出| I[结构化 JSON / 专业文本报告]
```


## 🚀 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 命令行使用
```bash
# 分析美股（人类可读报告）
python -m apps.cli.main AAPL

# 分析A股（JSON输出）
python -m apps.cli.main sh.600519 --format json

# 批量扫描
python -m apps.cli.main --batch --symbols "AAPL,MSFT,GOOGL"
```

### Claude Desktop 配置 (MCP)
📖 **详细配置指南**: 请查看 [`HOW_TO_USE.md`](HOW_TO_USE.md#2-claude-desktop-mcp-配置)

快速配置：
```json
"mcpServers": {
  "wyckoff": {
    "command": "python",
    "args": ["你的项目路径/apps/mcp/server.py"]
  }
}
```

**📚 更多使用方式**:
- CLI 详细用法 → [`HOW_TO_USE.md`](HOW_TO_USE.md)
- Python 库集成 → [`HOW_TO_USE.md`](HOW_TO_USE.md#python-库)
- MCP 故障排查 → [`HOW_TO_USE.md`](HOW_TO_USE.md#6-常见问题排查)

---

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| 📖 [README.md](README.md) | 项目概述（本文件） |
| 🧠 [SKILL.md](SKILL.md) | AI Agent 系统指令（威科夫方法论） |
| 📘 [HOW_TO_USE.md](HOW_TO_USE.md) | 详细使用指南（CLI / Python 库 / MCP 配置） |
| 📗 [references/](references/) | 威科夫理论文档和实战指南 |
| 📜 [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |

---

## 📁 项目结构

> **⚠️ 注意**：以下为简化导航，仅展示核心文件和目录。

```text
wyckoff-stock-analysis/
├── SKILL.md                 # [大脑] AI Agent 系统指令与路由规则
├── README.md                # [文档] 项目说明（本文件）
├── CHANGELOG.md             # [文档] 版本更新日志
├── src/                     # [库层] 纯库代码，可被任何应用导入
│   └── wyckoff/             #   └── 威科夫分析核心库
│       ├── facade.py        #       ⭐ WyckoffAnalyzer 统一入口
│       ├── core/            #       └── 核心计算引擎（30+ 模块）
│       │   ├── pattern_detector.py         # 形态识别 (v1.3增强)
│       │   ├── law_analyzer.py             # 威科夫定律分析 (v1.1增强)
│       │   ├── phase_coordinator.py        # 阶段协调器 (v1.1量化)
│       │   ├── meng_pattern_enhancer.py    # 孟洪涛方法增强 (v1.3新增)
│       │   ├── multi_timeframe_analyzer.py # 多周期共振 (v1.3增强)
│       │   ├── thresholds.py               # 动态阈值系统 (v1.3新增)
│       │   ├── data_fetcher.py             # 数据获取 (v1.3优化)
│       │   ├── report_generator.py         # 报告生成
│       │   ├── point_and_figure.py         # 点数图（因果法则）
│       │   ├── detectors/                  # 检测器目录
│       │   │   ├── base_detector.py        # 基类 (v1.2增强)
│       │   │   ├── classic_pattern_detector.py  # 经典形态 (v1.1/v1.2增强)
│       │   │   ├── strength_weakness_detector.py  # 强弱信号
│       │   │   └── ...                     # 其他检测器
│       │   └── ...                        # 其他核心模块
│       ├── services/        #       └── 外部服务接口
│       │   └── screener_service.py         # ⭐ 批量扫描服务 (v1.3优化)
│       ├── config/          #       └── 配置管理
│       │   └── settings.py               # Pydantic 阈值配置 (v1.3增强)
│       ├── schemas.py       #       ⭐ 强类型数据契约
│       ├── enums.py         #           枚举定义（ErrorCode, WyckoffPhase等）
│       ├── exceptions.py    #           异常定义
│       └── ...              #           其他模块
├── apps/                    # [应用层] 应用程序入口
│   ├── cli/                 #   └── 命令行工具
│   │   └── main.py          #       ⭐ CLI 入口
│   └── mcp/                 #   └── MCP 服务器
│       └── server.py        #       ⭐ MCP 服务器
├── tests/                   # [质量] 单元测试（92+ 测试用例）
│   ├── test_scoring.py      #       v1.1/v1.2 测试
│   ├── test_theory_fix.py   #       v1.0 理论修复测试
│   ├── test_*.py            #       15+ 测试文件
│   └── conftest.py          #       pytest 配置
├── references/              # [文档] 理论文档和实战指南
│   ├── wyckoff-theory-full.md    # 完整理论
│   ├── meng-hongtao-wyckoff-method.md  # 孟洪涛方法
│   └── ...                         # 其他参考文档
└── scripts/                 # [工具] 开发和维护脚本
    └── check_repo_claims.py      # ⭐ README 校验脚本
```

**架构原则：**
- 库层 (`src/wyckoff/`) 不反向依赖应用层 (`apps/`)
- 应用层仅调用库层的公共 API
- ⭐ 标记为常用或重要文件


**⚠️ 免责声明**：
> 本项目仅供学习和研究使用，不构成投资建议。股市有风险，投资需谨慎。交易是一场关于概率的修行，保护本金是第一优先级。 📈

---

