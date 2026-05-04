#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试孟洪涛增强模块的集成和功能
"""

import sys
import os
import io

# 设置UTF-8编码输出（Windows兼容）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from wyckoff.facade import WyckoffAnalyzer
from wyckoff.config.settings import WyckoffConfig


def test_spring_enhanced():
    """测试孟洪涛Spring增强检测"""
    print("=" * 70)
    print("测试1：孟洪涛Spring（震仓）5重过滤检测")
    print("=" * 70)

    # 使用一只可能经历Spring的股票
    analyzer = WyckoffAnalyzer("AAPL", "2y")

    print("\n正在获取数据...")
    if analyzer.fetch_data() is None:
        print("❌ 数据获取失败")
        return False

    print(f"✅ 数据获取成功: {len(analyzer.data)}条记录")
    print(f"   价格范围: {analyzer.data['Close'].min():.2f} - {analyzer.data['Close'].max():.2f}")

    # 使用孟洪涛增强检测
    print("\n使用孟洪涛5重过滤检测Spring...")
    spring_result = analyzer.pattern_detector.detect_spring_menhongtao()

    if spring_result.get('detected'):
        print("✅ 检测到Spring！")
        latest = spring_result.get('latest_spring', {})
        print(f"\nSpring详情:")
        print(f"  日期: {latest.get('date', 'N/A')}")
        print(f"  跌破价: {latest.get('breakdown_price', 0):.2f}")
        print(f"  支撑位: {latest.get('support_level', 0):.2f}")
        print(f"  收回价: {latest.get('recovery_price', 0):.2f}")
        print(f"  收回天数: {latest.get('recovery_days', 0)}天")
        print(f"  成交量比: {latest.get('vol_ratio', 0):.2f}x")
        print(f"  收盘位置: {latest.get('close_position', 0):.1f}%")
        print(f"  置信度: {latest.get('confidence', 0):.0f}/100")

        # 检查置信度
        confidence = latest.get('confidence', 0)
        if confidence >= 80:
            print(f"\n⭐⭐⭐ 高置信度Spring ({confidence:.0f}/100)")
            print("   建议：这是一个高质量的Spring信号，值得重点关注")
        elif confidence >= 60:
            print(f"\n⭐⭐ 中等置信度Spring ({confidence:.0f}/100)")
            print("   建议：Spring质量尚可，但需要等待更多确认")
        else:
            print(f"\n⭐ 低置信度Spring ({confidence:.0f}/100)")
            print("   建议：Spring质量不高，建议观望")

        return True
    else:
        print(f"❌ 未检测到Spring")
        print(f"   原因: {spring_result.get('reason', 'unknown')}")
        return False


def test_joc_enhanced():
    """测试孟洪涛JOC增强检测"""
    print("\n" + "=" * 70)
    print("测试2：孟洪涛JOC（跃过小溪）增强检测")
    print("=" * 70)

    # 使用一只可能经历JOC的股票
    analyzer = WyckoffAnalyzer("TSLA", "2y")

    print("\n正在获取数据...")
    if analyzer.fetch_data() is None:
        print("❌ 数据获取失败")
        return False

    print(f"✅ 数据获取成功: {len(analyzer.data)}条记录")

    # 使用孟洪涛增强检测JOC
    print("\n使用孟洪涛增强检测JOC...")
    joc_result = analyzer.pattern_detector.detect_joc_menhongtao()

    if joc_result.get('detected'):
        print("✅ 检测到JOC！")
        latest = joc_result.get('latest', {})
        print(f"\nJOC详情:")
        print(f"  日期: {latest.get('date', 'N/A')}")
        print(f"  小溪阻力位: {latest.get('creek_level', 0):.2f}")
        print(f"  突破收盘: {latest.get('close_price', 0):.2f}")
        print(f"  突破涨幅: {latest.get('breakout_pct', 0):.1f}%")
        print(f"  成交量比: {latest.get('volume_ratio', 0):.2f}x")
        print(f"  收盘位置: {latest.get('close_position', 0):.1f}%")
        print(f"  回测确认: {'是' if latest.get('test_detected') else '否'}")

        if latest.get('test_detected'):
            print(f"  回测日期: {latest.get('test_date', 'N/A')}")
            print(f"  回测量能: {latest.get('test_vol_ratio', 0):.2f}x")

        confidence = latest.get('confidence', 0)
        print(f"  置信度: {confidence:.0f}/100")

        if confidence >= 80:
            print(f"\n⭐⭐⭐ 高置信度JOC ({confidence:.0f}/100)")
            print("   建议：这是一个高质量的JOC信号，强烈建议关注回测买入机会")
            if latest.get('test_detected'):
                print("   ✓ JOC已回测确认，现在是最佳入场时机！")
        elif confidence >= 60:
            print(f"\n⭐⭐ 中等置信度JOC ({confidence:.0f}/100)")
            print("   建议：JOC质量尚可，等待回测确认后再入场")
        else:
            print(f"\n⭐ 低置信度JOC ({confidence:.0f}/100)")
            print("   建议：JOC质量不高，建议观望或等待更好机会")

        return True
    else:
        print(f"❌ 未检测到JOC")
        print(f"   原因: {joc_result.get('reason', 'unknown')}")
        return False


def test_vsa_signals():
    """测试VSA信号检测"""
    print("\n" + "=" * 70)
    print("测试3：VSA（Volume Spread Analysis）微观分析")
    print("=" * 70)

    # 使用一只股票测试VSA
    analyzer = WyckoffAnalyzer("NVDA", "1y")

    print("\n正在获取数据...")
    if analyzer.fetch_data() is None:
        print("❌ 数据获取失败")
        return False

    print(f"✅ 数据获取成功: {len(analyzer.data)}条记录")

    # 检测VSA信号
    print("\n检测VSA信号...")
    vsa_result = analyzer.pattern_detector.detect_vsa_menhongtao()

    signals_found = []

    # 检查No Supply
    no_supply = vsa_result.get('no_supply', {})
    if no_supply.get('detected'):
        latest = no_supply.get('latest', {})
        print(f"\n✅ 检测到No Supply（无供应）信号")
        print(f"   最新日期: {latest.get('date', 'N/A')}")
        print(f"   成交量比: {latest.get('vol_ratio', 0):.2f}x")
        print(f"   收盘位置: {latest.get('close_position', 0):.1f}%")
        print(f"   信号数量: {len(no_supply.get('signals', []))}个")
        signals_found.append('No Supply')

    # 检查No Demand
    no_demand = vsa_result.get('no_demand', {})
    if no_demand.get('detected'):
        latest = no_demand.get('latest', {})
        print(f"\n⚠️  检测到No Demand（无需求）信号")
        print(f"   最新日期: {latest.get('date', 'N/A')}")
        print(f"   成交量比: {latest.get('vol_ratio', 0):.2f}x")
        print(f"   信号数量: {len(no_demand.get('signals', []))}个")
        signals_found.append('No Demand')

    # 检查Stopping Volume
    stopping_vol = vsa_result.get('stopping_vol', {})
    if stopping_vol.get('detected'):
        latest = stopping_vol.get('latest', {})
        print(f"\n🛑 检测到Stopping Volume（停止行为）信号")
        print(f"   最新日期: {latest.get('date', 'N/A')}")
        print(f"   成交量比: {latest.get('vol_ratio', 0):.2f}x")
        print(f"   价格: {latest.get('price', 0):.2f}")
        print(f"   信号数量: {len(stopping_vol.get('signals', []))}个")
        signals_found.append('Stopping Volume')

    if signals_found:
        print(f"\n✅ VSA分析完成，发现 {len(signals_found)} 种信号")
        print(f"   信号类型: {', '.join(signals_found)}")
        print("\n交易建议:")
        if 'No Supply' in signals_found:
            print("   • No Supply：供应枯竭，可能是绝佳买入点")
        if 'No Demand' in signals_found:
            print("   • No Demand：需求不足，建议减仓或观望（A股做空困难）")
        if 'Stopping Volume' in signals_found:
            print("   • Stopping Volume：主力可能在底部吸收供应，等待Spring确认")
        return True
    else:
        print("\n⏳ 当前没有检测到明显的VSA信号")
        print("   建议：继续观察或等待其他信号")
        return False


def test_integration():
    """测试完整的系统集成"""
    print("\n" + "=" * 70)
    print("测试4：完整系统集成测试")
    print("=" * 70)

    # 测试多只股票
    test_symbols = ["AAPL", "MSFT", "GOOGL"]

    results = {
        'spring': 0,
        'joc': 0,
        'vsa': 0,
        'total': 0
    }

    for symbol in test_symbols:
        print(f"\n分析 {symbol}...")
        try:
            analyzer = WyckoffAnalyzer(symbol, "1y")
            if analyzer.fetch_data() is None:
                print(f"  ⚠️  数据获取失败，跳过")
                continue

            results['total'] += 1

            # 测试Spring检测
            spring = analyzer.pattern_detector.detect_spring_menhongtao()
            if spring.get('detected'):
                results['spring'] += 1
                print(f"  ✅ Spring: 检测到 (置信度: {spring.get('latest_spring', {}).get('confidence', 0):.0f})")
            else:
                print(f"  ➖ Spring: 未检测到")

            # 测试JOC检测
            joc = analyzer.pattern_detector.detect_joc_menhongtao()
            if joc.get('detected'):
                results['joc'] += 1
                print(f"  ✅ JOC: 检测到 (置信度: {joc.get('latest', {}).get('confidence', 0):.0f})")
            else:
                print(f"  ➖ JOC: 未检测到")

            # 测试VSA检测
            vsa = analyzer.pattern_detector.detect_vsa_menhongtao()
            vsa_count = sum([
                vsa.get('no_supply', {}).get('detected', False),
                vsa.get('no_demand', {}).get('detected', False),
                vsa.get('stopping_vol', {}).get('detected', False)
            ])
            if vsa_count > 0:
                results['vsa'] += 1
                print(f"  ✅ VSA: 检测到 {vsa_count} 种信号")
            else:
                print(f"  ➖ VSA: 无明显信号")

        except Exception as e:
            print(f"  ❌ 分析失败: {e}")

    # 汇总结果
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    print(f"分析股票数: {results['total']}")
    print(f"Spring检测: {results['spring']}/{results['total']} ({results['spring']/results['total']*100 if results['total'] > 0 else 0:.0f}%)")
    print(f"JOC检测: {results['joc']}/{results['total']} ({results['joc']/results['total']*100 if results['total'] > 0 else 0:.0f}%)")
    print(f"VSA检测: {results['vsa']}/{results['total']} ({results['vsa']/results['total']*100 if results['total'] > 0 else 0:.0f}%)")

    if results['total'] > 0:
        success_rate = (results['spring'] + results['joc'] + results['vsa']) / (results['total'] * 3) * 100
        print(f"\n总体信号检测率: {success_rate:.1f}%")

        if success_rate >= 50:
            print("✅ 系统集成测试通过！孟洪涛增强模块工作正常")
            return True
        else:
            print("⚠️  信号检测率较低，可能需要调整参数或选择更活跃的股票")
            return False
    else:
        print("❌ 未能完成任何测试")
        return False


def main():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("孟洪涛《新威科夫操盘法》增强模块 - 集成测试")
    print("=" * 70)
    print("\n基于孟洪涛书中290页内容的优化验证")
    print("测试项目：Spring 5重过滤、JOC增强检测、VSA微观分析\n")

    results = []

    # 测试1：Spring增强检测
    try:
        result = test_spring_enhanced()
        results.append(('Spring检测', result))
    except Exception as e:
        print(f"❌ Spring测试失败: {e}")
        results.append(('Spring检测', False))

    # 测试2：JOC增强检测
    try:
        result = test_joc_enhanced()
        results.append(('JOC检测', result))
    except Exception as e:
        print(f"❌ JOC测试失败: {e}")
        results.append(('JOC检测', False))

    # 测试3：VSA信号检测
    try:
        result = test_vsa_signals()
        results.append(('VSA检测', result))
    except Exception as e:
        print(f"❌ VSA测试失败: {e}")
        results.append(('VSA检测', False))

    # 测试4：完整集成
    try:
        result = test_integration()
        results.append(('系统集成', result))
    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        results.append(('系统集成', False))

    # 最终报告
    print("\n" + "=" * 70)
    print("最终测试报告")
    print("=" * 70)

    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name:15s}: {status}")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    print(f"\n总计: {passed_count}/{total_count} 测试通过")

    if passed_count == total_count:
        print("\n🎉 所有测试通过！孟洪涛增强模块已成功集成并可正常使用")
        return 0
    elif passed_count >= total_count * 0.5:
        print(f"\n⚠️  部分测试通过 ({passed_count}/{total_count})")
        print("   建议：检查失败的测试并调整参数")
        return 1
    else:
        print(f"\n❌ 多数测试失败 ({passed_count}/{total_count})")
        print("   建议：检查代码实现或数据源")
        return 2


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
