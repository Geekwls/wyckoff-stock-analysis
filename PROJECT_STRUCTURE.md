# 项目完整结构说明

**生成日期：** 2026年5月4日
**项目版本：** v4.2.0
**状态：** ✅ 结构合理，组织清晰

---

## 📊 模块统计

### src/wyckoff/（库层）

| 分类 | 模块数 | 说明 |
|------|--------|------|
| **core 主目录** | 20 | 核心分析引擎 |
| **core/detectors/** | 4 | 形态识别探测器 |
| **core/strategies/** | 2 | 数据源策略 |
| **config/** | 1 | 配置管理 |
| **services/** | 1 | 服务接口 |
| **根目录** | 5 | 公共接口 |
| **总计** | **33** | **库层模块总数** |

---

## 🏗️ 完整目录结构

```
wyckoff-stock-analysis/
├── 📄 项目根文件
│   ├── README.md                    # 项目说明（核心路径版）
│   ├── SKILL.md                     # AI Agent 技能定义
│   ├── requirements.txt             # Python 依赖
│   └── .gitignore                   # Git 忽略规则
│
├── 📦 src/                         # [库层] 纯库代码（33 个模块）
│   └── wyckoff/
│       ├── 📐 facade.py            # ⭐ 统一入口（WyckoffAnalyzer）
│       ├── 📋 schemas.py           # ⭐ 数据契约（Pydantic）
│       ├── ⚠️ exceptions.py        # 异常定义
│       ├── 🔢 error_codes.py       # 错误码
│       ├── 🛠️ utils.py             # 工具函数
│       │
│       ├── 🧠 core/                # 核心引擎（26 个模块）
│       │   ├── pattern_detector.py          # ⭐ 形态识别
│       │   ├── law_analyzer.py              # 威科夫定律
│       │   ├── data_fetcher.py              # 数据获取
│       │   ├── report_generator.py          # 报告生成
│       │   ├── orchestrator.py              # 编排层
│       │   ├── recommendation_engine.py     # 推荐引擎
│       │   ├── multi_timeframe_analyzer.py  # 多时间框架
│       │   ├── relative_strength_analyzer.py # 相对强度
│       │   ├── trading_plan_generator.py    # 交易计划
│       │   ├── meng_pattern_enhancer.py     # 孟洪涛增强
│       │   ├── sentiment_analyzer.py         # 情绪分析
│       │   ├── backtest_engine.py           # 回测引擎
│       │   ├── signal_extractor.py          # 信号提取
│       │   ├── symbol_resolver.py           # 代码解析
│       │   ├── datasource_factory.py        # 数据源工厂
│       │   ├── datasource_strategy.py       # 数据源策略
│       │   ├── cache_service.py             # 缓存服务
│       │   ├── cache.py                     # LRU 缓存
│       │   ├── enums.py                     # 枚举定义
│       │   └── utils.py                     # 工具函数
│       │
│       │   ├── 🔍 detectors/         # 形态探测器（4 个）
│       │   │   ├── classic_pattern_detector.py  # 经典形态
│       │   │   ├── phase_identifier.py         # 阶段识别
│       │   │   ├── strength_weakness_detector.py # 强弱度
│       │   │   └── trading_range_detector.py     # 交易区间
│       │   │
│       │   └── 📊 strategies/          # 数据源策略（2 个）
│       │       ├── baostock_strategy.py   # A 股策略
│       │       └── yfinance_strategy.py   # 全球市场策略
│       │
│       ├── ⚙️ config/              # 配置（1 个模块）
│       │   └── settings.py          # Pydantic 配置
│       │
│       └── 🔄 services/            # 服务（1 个模块）
│           └── screener_service.py  # 批量扫描服务
│
├── 🚀 apps/                        # [应用层] 应用入口（2 个应用）
│   ├── 💻 cli/
│   │   └── main.py                 # ⭐ CLI 工具
│   └── 🔌 mcp/
│       └── server.py               # ⭐ MCP 服务器
│
├── 🧪 tests/                       # 测试（90+ 用例，14 文件）
│   ├── test_*.py                   # 测试文件
│   └── conftest.py                 # pytest 配置
│
├── 📚 references/                  # 文档（11 个文件）
│   ├── wyckoff-theory-full.md           # 完整理论
│   ├── meng-hongtao-wyckoff-method.md  # 孟洪涛方法
│   ├── meng-practical-guide.md         # 实战指南
│   ├── optimized-strategy.md           # 优化策略
│   ├── china-market-guide.md           # A 股指南
│   ├── common-pitfalls.md              # 常见错误
│   ├── learning-path.md                # 学习路径
│   ├── quick-reference.md              # 快速参考
│   ├── tool-integration-guide.md       # 工具集成
│   ├── analysis-example.md             # 分析示例
│   └── chart-examples/                 # 图表示例
│       ├── accumulation-examples.md
│       ├── distribution-examples.md
│       ├── failed-patterns.md
│       └── spring-upthrust-examples.md
│
└── 🔧 scripts/                     # 维护脚本
    ├── check_repo_claims.py        # ⭐ README 校验
    └── analyze_skill.py            # Skill 审核
```

---

## 🎯 组织原则

### 1. 分层架构

```
应用层 (apps/)
    ↓ 仅调用公共 API
库层 (src/wyckoff/)
    ↓ 不依赖应用层
```

### 2. 模块分类

| 类型 | 位置 | 数量 | 职责 |
|------|------|------|------|
| **公共接口** | `src/wyckoff/*.py` | 6 | 对外 API |
| **核心引擎** | `src/wyckoff/core/*.py` | 20 | 分析逻辑 |
| **形态识别** | `src/wyckoff/core/detectors/*.py` | 4 | 探测器 |
| **数据策略** | `src/wyckoff/core/strategies/*.py` | 2 | 数据源 |
| **配置管理** | `src/wyckoff/config/*.py` | 1 | 配置 |
| **服务接口** | `src/wyckoff/services/*.py` | 1 | 服务 |

### 3. 依赖关系

```
facade.py (统一入口)
    ↓
orchestrator.py (编排层)
    ↓
├─ pattern_detector.py
├─ law_analyzer.py
├─ data_fetcher.py
├─ report_generator.py
└─ ... (其他核心模块)
    ↓
detectors/, strategies/ (底层模块)
```

---

## ✅ 结构评估

### 优点

| 优点 | 说明 |
|------|------|
| **分层清晰** | 库层/应用层完全分离 |
| **职责明确** | 每个模块单一职责 |
| **易于扩展** | 新增形态/策略都很方便 |
| **可测试性** | 90+ 测试用例覆盖 |
| **可维护性** | 33 个模块组织合理 |

### 复杂度

| 维度 | 评估 | 说明 |
|------|------|------|
| **模块数量** | 🟡 中等 | 33 个模块，规模适中 |
| **目录深度** | 🟢 良好 | 最深 3 层（core/detectors/） |
| **耦合度** | 🟢 低 | 模块间依赖清晰 |
| **内聚度** | 🟢 高 | 相关功能集中 |

---

## 📝 维护建议

### 添加新功能

1. **新增形态识别**
   - 在 `core/detectors/` 创建新文件
   - 在 `pattern_detector.py` 中集成

2. **新增数据源**
   - 在 `core/strategies/` 创建新策略
   - 在 `datasource_factory.py` 注册

3. **新增服务**
   - 在 `services/` 创建新服务
   - 通过 `facade.py` 暴露

### 文档同步

修改结构后：
1. 运行 `python scripts/check_repo_claims.py`
2. 更新 README.md 的"项目导航"
3. CI 会自动检查文档一致性

---

## 🎉 总结

**当前项目结构：**
- ✅ 33 个库层模块，组织合理
- ✅ 分层架构，职责清晰
- ✅ 90+ 测试用例，质量保证
- ✅ 文档校验，防止漂移

**复杂度评估：**
- 🟡 中等复杂度（33 模块）
- 🟢 低耦合（依赖清晰）
- 🟢 高内聚（相关聚合）

**结论：** 结构合理，组织清晰，可维护性强。

---

**最后更新：** 2026年5月4日
**校验脚本：** `python scripts/check_repo_claims.py`
**以目录实际结构为准**
