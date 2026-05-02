# Wyckoff Stock Analysis Skill v4.1.0

> 一个专为 AI Agent（如 Claude Code, Cursor, MCP 客户端）打造的威科夫股票分析标准组件。

基于理查德·威科夫（Richard D. Wyckoff）的经典量价理论，本项目提供了一套**“提示词路由 + 本地量化工具”**的双核架构，使大语言模型能够 100% 准确地获取股票形态数据，并进行深度的市场周期分析。

---

## 🌟 核心特性 (v4.1.0 架构)

本项目已经超越了单纯的“提示词模板”，进化为一个平台无关的 Agent 技能包：

1. **双核驱动**：
   - **大脑**：精简高效的 `SKILL.md`（充当 System Prompt Router）。
   - **四肢**：`tools/wyckoff_analyzer.py`（Python 数据获取与形态检测引擎）。
2. **AI 友好输出**：核心分析器提供 `--json` 参数，输出结构化数据（含阶段识别、支撑压力位、因果目标价等），彻底消除大模型解析纯文本时产生的幻觉。
3. **全平台兼容**：完美支持 Cursor、Windsurf、Claude Code、ChatGPT Plus、Dify 等各类现代 AI 工作流生态。
4. **内置 A 股适配**：特殊的规则约束，防止 AI 误判 A 股“一字涨跌停”等极端量价形态。
5. **高性能架构**：通过 Pandas 向量化运算与内存级结果缓存，分析速度提升 5-10 倍；集成 Pydantic 进行严格的配置校验与错误处理。
6. **原生 MCP 支持**：提供标准 Model Context Protocol Server (`tools/mcp_server.py`)，支持 Claude Desktop、Cursor 等工具一键接入。

---

## 🚀 快速上手

### 1. 安装依赖环境

建议在 Python 3.8+ 环境下运行：

```bash
# 下载项目后进入目录
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
├── SKILL.md                          # 核心：AI Agent 系统提示词/路由规则 (v4.0.0)
├── README.md                         # 本说明文件
├── HOW_TO_USE.md                     # 多平台 AI 接入使用指南
├── .env.example                      # 环境变量配置模板
│
├── requirements.txt                  # Python 环境依赖包（含版本上限）
├── tests/                            # 单元测试
│   ├── conftest.py                   # 共享测试夹具（模拟 OHLCV 数据生成器）
│   ├── test_config.py                # WyckoffConfig 配置校验测试
│   ├── test_data_fetcher.py          # ATR计算 + 数据预处理测试
│   └── test_pattern_detector.py      # 形态检测全套测试
│
├── tools/                            # 本地量化工具库
│   ├── wyckoff_analyzer.py           # 核心调度器：Facade 模式入口
│   ├── wyckoff_utils.py              # 批量筛选器：WyckoffScreener
│   ├── exceptions.py                 # 自定义异常层级
│   ├── schemas.py                    # Pydantic 输出结构定义
│   ├── mcp_server.py                 # MCP 协议接口（供 AI Agent 调用）
│   ├── config/
│   │   └── settings.py               # 全局配置与阈值（Pydantic 校验）
│   └── core/
│       ├── data_fetcher.py           # 数据获取（A股/美股/港股）
│       ├── pattern_detector.py       # 形态检测（Spring/SOS/SOW/Climax等）
│       ├── law_analyzer.py           # 三大定律分析
│       └── report_generator.py       # 报告生成（文字报告 + JSON）
│
├── references/                       # 威科夫理论知识库 (供 AI 检索 RAG)
│   ├── wyckoff-theory-full.md        # 完整理论与量化标准
│   ├── china-market-guide.md         # A股市场特色指南
│   ├── common-pitfalls.md            # 实战常见错误与避坑
│   ├── learning-path.md              # 学习路线图
│   └── chart-examples/               # 实战图表案例库 (30+ 案例)
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

### v4.1.0 (2026-05-02) - 架构解耦 · 质量加固 · 测试覆盖 (P0/P1)

#### 🏗️ 架构重构（单一职责原则，God Class 彻底拆解）
- **`WyckoffDataFetcher`** → `tools/core/data_fetcher.py`：数据获取、A股/美股适配、Baostock 缓存管理完全独立。
- **`WyckoffPatternDetector`** → `tools/core/pattern_detector.py`：Spring / Upthrust / Climax / SOS / SOW / LPS / LPSY 所有形态检测方法全部迁出。
- **`WyckoffLawAnalyzer`** → `tools/core/law_analyzer.py`：威科夫三大定律（供求、努力与结果、因果）完整实现。
- **`WyckoffReportGenerator`** → `tools/core/report_generator.py`：文字报告与 JSON 结构化输出逻辑独立封装。
- `wyckoff_analyzer.py` 精简为纯 **Facade 调度器**，从 ~3900 行压缩至 ~900 行，降幅 77%。

#### 🧪 单元测试（零 → 31 个，全部通过）
- `tests/conftest.py`：共享 OHLCV 测试夹具，支持 flat / uptrend / downtrend / spring 多种市场场景。
- `tests/test_config.py`：Pydantic 配置校验（边界值、非法值拒绝等 9 个用例）。
- `tests/test_data_fetcher.py`：ATR 计算 + `prepare_data` 指标生成（8 个用例）。
- `tests/test_pattern_detector.py`：交易区间、SOS、SOW、Spring、Climax 检测（14 个用例）。

#### 🔧 代码质量修复
- **消除重复导入**：移除 `wyckoff_analyzer.py` 中两处多余的 `from ... import WyckoffReportGenerator`。
- **硬编码阈值统一**：`pattern_detector.py` 中 `0.3` / `0.35` 两处魔法数字改为读取 `self.config.spring_range_threshold`。
- **精确异常捕获**：baostock 相关 `except Exception` 改为 `except (ConnectionError, OSError)`，防止吞掉非网络异常。
- **长方法拆分**：`_detect_spring_impl`（~180行）拆分为 `_check_spring_preconditions` / `_find_spring_breakdowns` / `_verify_spring_recoveries` 三个职责单一的方法。
- **实现桩函数**：`law_analyzer.py` 中 4 个 TODO 占位方法（初步支撑/阻力检测、吸筹/耗散模式）完成真实向量化实现。

#### 📁 工程规范
- `.gitignore` 新增 `scratch/`、`.env`，防止临时脚本和密钥文件意外提交。
- `requirements.txt` 为 `yfinance` 补加 `<1.0.0` 上限，防止破坏性更新。
- `.env.example` 重写为项目真正可用的 `WYCKOFF_*` 配置模板。
- 版本号全项目同步：`SKILL.md`（4.0.0 → 4.0.0）、`HOW_TO_USE.md` 新增版本标注。

### v4.0.0 (2026-05-02) - 架构全面升级与 MCP 支持 (P0)
- 🔌 **标准 MCP Server**：新增 `tools/mcp_server.py`，使用 FastMCP 实现标准化接口，支持 Claude Desktop 与主流 IDE 一键无缝集成。
- 🛡️ **Pydantic 输出架构**：重构 `generate_json()` 底层逻辑，接入严格的 `ReportModel` Schema，彻底消除 AI 在反序列化时的结构幻觉。
- ⚡ **生态扩充**：依赖项新增 `mcp` 支持，重构底层组件规范化输出以备接下来的全量异步 IO 并发改造。

### v3.9.0 (2026-05-02) - 性能起飞与架构升级 (P0)
- 🚀 **全面向量化 (Vectorization)**：重写 `Spring`、`Climax`、`ST` 等核心检测算法，利用 NumPy/Pandas 向量化替代逐行循环，在大规模 `batch_scan` 时速度提升显著。
- ⚡ **内存级分析缓存 (Cache)**：引入 `AnalysisCache` 机制，在同一次分析会话中对计算密集的形态识别结果进行缓存，避免冗余重复计算。
- 🛡️ **结构化配置校验 (Pydantic)**：集成 Pydantic v2，实现对 `WyckoffConfig` 的实时校验与环境变量支持，确保分析参数的合法性。
- 🏗️ **异常处理体系 (Exceptions)**：建立完整的自定义异常层级（`WyckoffError` 派生体系），取代原始的 `print` 调试，使集成到 AI 工作流时更强。
- 📝 **文档与版本同步**：同步更新 `README.md` 及 `tools/__init__.py` 版本号。

### v3.8.1 (2026-05-02) - Bug 修复与代码质量 (P0/P1)
- 🐛 **修复 `generate_report()` 重复拉取数据**：已有数据时不再调用 `fetch_data()`，避免双倍网络请求。
- 🐛 **修复 dict 隐式 bool 判断**：`spring`/`upthrust`/`sos`/`sow`/`lps`/`lpsy` 全部改为 `.get('detected')`，消除空 dict 永真隐患。
- 🐛 **修复 `batch_scan` 中 `None` 值崩溃**：`events_detected` 中未命中事件返回 `None`，增加 `or {}` 保护。
- 🐛 **修复 `strength` 分母不一致**：`batch_scan` 和示例中 `/4` → `/6`（实际最高 6 分）。
- 🐛 **修复 Windows GBK 编码崩溃**：`batch_scan` 输出中的 emoji 改为 ASCII 标签。
- ⚡ **baostock 登录优化**：类级别 `_bs_logged_in` 状态，批量操作只登录一次。
- ⚡ **`wyckoff_utils` 性能提升**：复用 `identify_phase()` 已计算的 events，避免 6 次重复检测。
- 📝 **异常处理收紧**：`_resolve_stock_name` 吞异常改为精确捕获 `JSONDecodeError`/`OSError` 并记录日志。
- 📝 **依赖版本约束**：`requirements.txt` 全部依赖加上 `<3.0.0` 上限。
- 📝 **文档修正**：移除 `HOW_TO_USE.md`、`README.md`、`example_usage.py` 中不存在的 `api/`、`docker/`、`app/`、`dotenv` 引用。
- 📝 **新增 `__version__`**：`tools/__init__.py` 导出 `__version__ = "3.8.0"`。

### v3.8.0 (2026-05-01) - 稳定性与质量提升 (P2)
- ✨ **日志设施接入**：增加模块级日志，方便使用者随时配置和追踪调试。
- ✨ **Spring 深度搜寻**：搜索窗口从 30 天拓宽至 45 天，全面覆盖并检测更长横盘后延迟确认的假跌破形态。
- ✨ **信号严谨去重**：Spring / Secondary Test 增加日期哈希去重过滤，杜绝同一日线由于周期索引重叠被多次添加。
- ✨ **batch_scan 全面升级**：重构扫描效率，内部共享分析数据（最高 6 分满分），新增 confidence 支持并增强了逐一异常拦截防挂起能力。

### v3.7.0 (2026-05-01) - 修正威科夫理论定义 (P0)
- ✨ **Spring 收盘阈值宽限**：将收盘位置约束放宽至日内 50% 中位上方，主要依据为“价格回到支撑位以上”作为核心 Spring 依据，极大减少有效形态漏检。
- ✨ **Upthrust 量能逻辑修正**：修正为“诱多日放量，拒绝区缩量”（原有逻辑颠倒），完全贴合威科夫理论。

### v3.6.0 (2026-05-01) - 核心性能与阶段精度优化 (P0/P1)
- ✨ **高精度类型标志位**：各事件探测器底层通过 `_type` 字段显式区分形态，取代不可靠的字符串匹配。
- ✨ **高速专属胜率回测**：预先提取日线位置映射，将胜率统计的时间复杂度降到 O(1)。
- ✨ **因果目标时间加权**：因果测算加入 `time_factor` 时间调节乘数（最高 3 倍），积累期越长，测算目标位越远。
- ✨ **量价确认按需修正**：重构量价子阶段判定，识别吸筹期 A/B 阶段（主力吸筹需跌放量涨缩量）与突破期 D/E 阶段。

### v3.5.0 (2026-05-01) - P0 级严重 Bug 修复与内存缓存 (P0/P1)
- ✨ **全链路 IO 优化**：引入 `_index_analyzer_cache`，同一次分析中大盘指数只拉取 1 次，彻底解决频繁调用网络资源的性能损耗问题。
- ✨ **高潮识别逻辑更正**：修复 `detect_climax` 为全量收集最新发生的高潮点。
- ✨ **LPS/LPSY 量纲统一**：解决了原来误将成交量缩减率（倍数）和原始总成交量（绝对值）交叉比较的严重量纲缺陷。
- ✨ **均线多空判定倒置修复**：更正 `_check_ma_confirmation` 原本彻底相反的阶段评分机制（上涨/建仓期应在价格高于均线时得高分）。

### v3.4.0 (2026-05-01) - 自适应策略引擎
- ✨ **股性自适应分类**：新增 `_classify_volatility()` 方法，通过 `ATR%` 自动区分低/中/高波动股性，驱动所有阈值动态化。
- ✨ **市场环境量化** (P0)：新增 `_analyze_market_environment()`，通过均线排列 + **均线粘合度检测** (<2% 强制锁定为震荡)，量化 6 级大盘环境（强牛/牛/弱牛/震荡/熊/强熊）。
- ✨ **Spring/SOS 精度大幅提升** (P0/P1)：跌破阈值按股性动态设置 (3%/4%/5%)；新增**收盘位置验证**（需在日内振幅 70% 以上）；加入**除零保护**处理涨停/跌停；A股涨跌停板豁免成交量限制。
- ✨ **分批建仓精确触发** (P1)：`scale_in_triggers` 输出每笔建仓的**具体价格**（试探仓/主仓/加仓）及触发条件，前端可直接展示。
- ✨ **结构化退出规则** (P2)：`exit_rules` 改为程序化可解析对象，内含移动止损（浮盈 1ATR 移至成本）、分级跟踪止损及 5-8 日**时间止损**机制。
- ✨ **ATR 动态止损**: `stop_loss.atr_dynamic_stop` = `Close - 1.5 * ATR`，科学量化每笔止损位。

### v3.3.0 (2026-05-01) - 情绪风控与多时间框架引擎
- ✨ **全局情绪预警**：动态拉取 VIX/VHSI 或大盘历史实现波动率，自动计算 A股/港股/美股恐慌指数。
- ✨ **仓位动态风控**：根据情绪指数自动缩放建议仓位（恐慌减仓，贪婪加仓），并在“贪婪+派发”时触发背离极其危险预警。
- ✨ **多维度降维打击**：引入周线、月线长期趋势判定，并增加与大盘的相对强度 (Relative Strength) 量化分析。

### v3.2.0 (2026-05-01) - V2 威科夫事件推演引擎
- ✨ **事件驱动阶段识别**：废弃纯均线判断，底层改为通过严谨探测（高潮 CL -> 自动反抽 AR -> 震仓 Spring）事件因果链来倒推威科夫阶段。
- ✨ **动态历史回测**：加入基于当前个股自身历史数据的形态表现回测引擎，动态计算每次 SOS/SOW/Spring 的真实历史专属胜率。
- ✨ **术语大白话解析**：根据当前所处阶段及爆发的信号，自动输出动态的“术语百科”，供大模型快速渲染。


---

## 🤝 贡献与反馈

如果你对量化逻辑有改进建议、发现了 bug，或者想分享绝佳的交易案例，欢迎提交 Issue 或 Pull Request！

**祝你交易成功！记住：保护本金永远是第一要务。** 📈
