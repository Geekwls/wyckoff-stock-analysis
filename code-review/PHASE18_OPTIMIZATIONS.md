# Phase 18 威科夫审查优化清单

**日期：** 2026-05-23  
**前置：** Phase 17 已完成

---

## Phase 18a — EventArbitrator 派发/吸筹 C→D 配对

| ID | 问题 | 修复 |
|----|------|------|
| P1-1 | SOW+FTI 无专用规则 | `_arbitrate_sow_fti`：派发语境 FTI 优先 |
| P1-2 | SOS+JOC 无专用规则 | `_arbitrate_sos_joc`：吸筹语境 JOC 优先 |
| P1-3 | FTI 后 SOW 再现未处理 | SOW 在 FTI 后 ≤14 天 → 冰层突破可能失败 |

## Phase 18b — 验证脚本

| ID | 问题 | 修复 |
|----|------|------|
| P2-1 | 无法只看 A 股 / 限流时全失败 | `--ashare-only` / `--symbols` |
| P2-2 | Yahoo 429 无离线回退 | `--cache-only` + `WYCKOFF_YF_CACHE_ONLY` |
| P2-3 | 仲裁结果不可见 | 输出 `arbitration.dominant` / `reason` |

---

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_phase18_optimizations \
  tests.test_phase17_optimizations -q
```

## 复现

```bash
# 仅 A 股（推荐）
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --ashare-only

# Yahoo 限流时用本地过期缓存
PYTHONPATH=src .venv/bin/python scripts/validate_real_stocks.py --cache-only
```
