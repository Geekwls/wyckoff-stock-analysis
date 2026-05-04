#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量扫描功能测试
"""

import sys
import os

# UTF-8 输出支持
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wyckoff.facade import batch_scan
from wyckoff.services.screener_service import ScreenerService


def test_batch_scan_function():
    """测试 batch_scan 便捷函数"""
    print("=" * 70)
    print("测试1：batch_scan 便捷函数")
    print("=" * 70)

    # 测试快速扫描
    symbols = ["AAPL", "MSFT"]

    print(f"\n扫描股票: {symbols}")
    print("模式: quick (快速扫描)")

    try:
        result = batch_scan(
            symbols,
            period="1y",
            scan_mode="quick",
            show_progress=True,
            max_workers=2
        )

        print(f"\n✅ 扫描完成!")
        print(f"\n统计摘要:")
        summary = result['summary']
        print(f"  扫描总数: {summary['total_scanned']}")
        print(f"  信号数量: {summary['signal_count']}")
        print(f"  入场机会: {summary['entry_count']}")
        print(f"  失败数量: {summary['failed_count']}")

        print(f"\n阶段分布:")
        for phase, count in summary['phase_distribution'].items():
            print(f"  {phase}: {count}")

        print(f"\n顶级机会 (TOP {len(result['top_picks'])}):")
        for i, pick in enumerate(result['top_picks'], 1):
            score = pick.get('weighted_score', pick.get('strength', 0))
            phase = pick.get('phase', 'Unknown')
            symbol = pick.get('symbol', 'Unknown')
            entry_tag = " [ENTRY]" if pick.get('is_entry') else ""
            print(f"  {i}. {symbol}: {phase} (评分: {score}){entry_tag}")

        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_screener_service_batch_scan():
    """测试 ScreenerService.batch_scan 方法"""
    print("\n" + "=" * 70)
    print("测试2：ScreenerService.batch_scan 方法")
    print("=" * 70)

    screener = ScreenerService()
    symbols = ["AAPL", "MSFT"]

    print(f"\n扫描股票: {symbols}")
    print("模式: quick")

    try:
        result = screener.batch_scan(
            symbols,
            period="1y",
            scan_mode="quick",
            show_progress=False
        )

        print(f"\n✅ 方法调用成功!")
        print(f"返回键: {list(result.keys())}")
        print(f"结果数量: {len(result['results'])}")

        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_batch_scan_accumulation_mode():
    """测试积累期筛选模式（暂不支持）"""
    print("\n" + "=" * 70)
    print("测试3：积累期筛选模式（预期不支持）")
    print("=" * 70)

    symbols = ["AAPL"]
    print(f"\n扫描股票: {symbols}")
    print("模式: accumulation (预期应抛出 ValueError)")

    try:
        result = batch_scan(
            symbols,
            period="1y",
            scan_mode="accumulation",
            show_progress=False
        )
        print(f"\n⚠️  预期应抛出异常，但返回了结果")
        return False

    except ValueError as e:
        if "不支持的扫描模式" in str(e):
            print(f"\n✅ 正确抛出异常: {e}")
            return True
        else:
            print(f"\n❌ 抛出了错误的异常: {e}")
            return False
    except Exception as e:
        print(f"\n❌ 抛出了意外的异常: {e}")
        return False


def test_batch_scan_multiple_modes():
    """测试多种扫描模式（仅支持quick）"""
    print("\n" + "=" * 70)
    print("测试4：多种扫描模式验证（quick 成功，其他应失败）")
    print("=" * 70)

    symbols = ["AAPL"]
    modes = {
        "quick": True,      # 应成功
        "accumulation": False,  # 应失败
        "distribution": False   # 应失败
    }

    print(f"\n测试股票: {symbols}")
    print(f"测试模式: {list(modes.keys())}")

    results = {}
    for mode, should_succeed in modes.items():
        try:
            print(f"\n测试模式: {mode}...")
            result = batch_scan(
                symbols,
                period="1y",
                scan_mode=mode,
                show_progress=False
            )
            results[mode] = (should_succeed, "OK")
            status = "✅" if should_succeed else "⚠️ "
            print(f"  {status} {mode} 模式成功（预期: {'成功' if should_succeed else '失败'}）")
        except ValueError as e:
            # 预期的异常（不支持的扫描模式）
            if "不支持的扫描模式" in str(e):
                results[mode] = (not should_succeed, "EXPECTED_FAIL")
                status = "✅" if not should_succeed else "❌"
                print(f"  {status} {mode} 模式正确抛出异常（预期: {'失败' if not should_succeed else '成功'}）")
            else:
                results[mode] = (False, f"WRONG_ERROR: {e}")
                print(f"  ❌ {mode} 模式抛出错误异常: {e}")
        except Exception as e:
            results[mode] = (False, f"UNEXPECTED: {e}")
            print(f"  ❌ {mode} 模式抛出意外异常: {e}")

    success_count = sum(1 for (actual, _) in results.values() if actual)
    print(f"\n模式测试结果: {success_count}/{len(modes)} 通过")

    return success_count == len(modes)


def test_batch_scan_result_structure():
    """测试返回结果结构"""
    print("\n" + "=" * 70)
    print("测试5：返回结果结构验证")
    print("=" * 70)

    symbols = ["AAPL"]

    try:
        result = batch_scan(symbols, scan_mode="quick", show_progress=False)

        # 验证必需键
        required_keys = ["results", "summary", "top_picks", "failed", "scan_mode"]
        missing_keys = [k for k in required_keys if k not in result]

        if missing_keys:
            print(f"❌ 缺少必需键: {missing_keys}")
            return False

        print("✅ 返回结果结构正确")
        print(f"  包含键: {list(result.keys())}")

        # 验证 summary 结构
        summary = result['summary']
        required_summary_keys = ["total_scanned", "signal_count", "entry_count",
                                  "high_score_count", "failed_count", "phase_distribution"]
        missing_summary_keys = [k for k in required_summary_keys if k not in summary]

        if missing_summary_keys:
            print(f"❌ summary 缺少必需键: {missing_summary_keys}")
            return False

        print("✅ summary 结构正确")
        print(f"  包含键: {list(summary.keys())}")

        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("批量扫描功能 - 测试套件")
    print("=" * 70)

    tests = [
        ("batch_scan便捷函数", test_batch_scan_function),
        ("ScreenerService.batch_scan方法", test_screener_service_batch_scan),
        ("积累期筛选模式", test_batch_scan_accumulation_mode),
        ("多种扫描模式", test_batch_scan_multiple_modes),
        ("返回结果结构", test_batch_scan_result_structure),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} 测试异常: {e}")
            results.append((test_name, False))

    # 最终报告
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)

    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name:30s}: {status}")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    print(f"\n总计: {passed_count}/{total_count} 测试通过")

    if passed_count == total_count:
        print("\n🎉 所有测试通过！批量扫描功能正常")
        return 0
    else:
        print(f"\n⚠️  部分测试失败 ({passed_count}/{total_count})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
