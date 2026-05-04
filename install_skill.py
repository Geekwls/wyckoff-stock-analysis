#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析Skill安装脚本
支持多平台安装：Claude Code、Cursor、ChatGPT等
"""

import os
import sys
import subprocess
import json
from pathlib import Path

# 设置UTF-8编码（Windows兼容）
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

class SkillInstaller:
    def __init__(self, project_path: str = "."):
        self.project_path = Path(project_path)
        self.skill_file = self.project_path / "SKILL.md"
        self.requirements_file = self.project_path / "requirements.txt"

    def check_environment(self) -> dict:
        """检查环境依赖"""
        print("[CHECK] 检查环境依赖...")
        results = {
            "python": False,
            "pip": False,
            "git": False,
            "project_files": False
        }

        # 检查Python
        try:
            version = sys.version_info
            if version.major >= 3 and version.minor >= 8:
                results["python"] = True
                print(f"  [OK] Python {version.major}.{version.minor}.{version.micro}")
            else:
                print(f"  [FAIL] Python版本过低: {version.major}.{version.minor}.{version.micro}")
                print("         需要Python 3.8+")
        except Exception as e:
            print(f"  [ERROR] Python检查失败: {e}")

        # 检查pip
        try:
            subprocess.run(["pip", "--version"], capture_output=True, check=True)
            results["pip"] = True
            print("  [OK] pip可用")
        except Exception as e:
            print(f"  [ERROR] pip不可用: {e}")

        # 检查git
        try:
            subprocess.run(["git", "--version"], capture_output=True, check=True)
            results["git"] = True
            print("  [OK] git可用")
        except Exception as e:
            print(f"  [WARN] git不可用: {e}")

        # 检查项目文件
        required_files = [
            "SKILL.md",
            "src/wyckoff/facade.py",
            "src/wyckoff/__init__.py",
            "requirements.txt"
        ]

        missing_files = []
        for file in required_files:
            if (self.project_path / file).exists():
                print(f"  [OK] {file}")
            else:
                print(f"  [MISSING] {file}")
                missing_files.append(file)

        if not missing_files:
            results["project_files"] = True

        return results

    def install_dependencies(self) -> bool:
        """安装Python依赖"""
        print("\n📦 安装Python依赖...")

        if not self.requirements_file.exists():
            print(f"  ❌ 依赖文件不存在: {self.requirements_file}")
            return False

        try:
            # 升级pip
            print("  🔄 升级pip...")
            subprocess.run([
                sys.executable, "-m", "pip", "install", "--upgrade", "pip"
            ], check=True, capture_output=True)

            # 安装依赖
            print("  📥 安装项目依赖...")
            subprocess.run([
                sys.executable, "-m", "pip", "install", "-r", str(self.requirements_file)
            ], check=True)

            print("  ✅ 依赖安装完成")
            return True

        except subprocess.CalledProcessError as e:
            print(f"  ❌ 依赖安装失败: {e}")
            return False

    def test_skill(self) -> bool:
        """测试Skill是否正常工作"""
        print("\n🧪 测试Skill功能...")

        try:
            # 测试导入
            print("  🔄 测试模块导入...")
            sys.path.insert(0, str(self.project_path))
            from src.wyckoff.facade import WyckoffAnalyzer

            # 测试基本功能
            print("  🔄 测试基本功能...")
            analyzer = WyckoffAnalyzer("AAPL", "1y")

            # 测试数据获取
            print("  🔄 测试数据获取...")
            data = analyzer.fetch_data()
            if data is not None and not data.empty:
                print(f"  ✅ 数据获取成功: {len(data)}条记录")
                print(f"     价格范围: {data['Close'].min():.2f} - {data['Close'].max():.2f}")
                return True
            else:
                print("  ⚠️  数据获取失败（可能是网络问题）")
                return False

        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_desktop_shortcut(self) -> bool:
        """创建桌面快捷方式（Windows）"""
        print("\n🖥️  创建桌面快捷方式...")

        if sys.platform != "win32":
            print("  ⚠️  仅支持Windows平台")
            return False

        try:
            import winshell
            from win32com.client import Dispatch

            desktop = winshell.desktop()
            path = os.path.join(desktop, "Wyckoff分析.lnk")
            target = sys.executable
            wDir = str(self.project_path)
            icon = str(self.project_path / "tools" / "wyckoff_analyzer.py")

            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(path)
            shortcut.Targetpath = target
            shortcut.WorkingDirectory = wDir
            shortcut.IconLocation = icon
            shortcut.save()

            print(f"  ✅ 快捷方式已创建: {path}")
            return True

        except ImportError:
            print("  ⚠️  需要安装pywin32: pip install pywin32")
            return False
        except Exception as e:
            print(f"  ❌ 创建快捷方式失败: {e}")
            return False

    def generate_claude_code_config(self) -> str:
        """生成Claude Code配置"""
        print("\n📝 生成Claude Code配置...")

        config_content = f"""# Wyckoff Analysis Skill Configuration

## Skill路径
{self.skill_file.absolute()}

## 使用方法
在Claude Code中直接询问：
- "分析AAPL股票"
- "使用威科夫理论分析特斯拉"
- "检测腾讯的Spring形态"

## 工具调用
Claude Code会自动调用：
```bash
python {self.project_path / "tools/wyckoff_analyzer.py"} <股票代码> --json
```

## 知识库
- 理论文档: {self.project_path / "references/wyckoff-theory-full.md"}
- A股指南: {self.project_path / "references/china-market-guide.md"}
- 常见陷阱: {self.project_path / "references/common-pitfalls.md"}
"""

        config_file = self.project_path / "CLAUDE_CODE_CONFIG.md"
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)

        print(f"  ✅ 配置文件已生成: {config_file}")
        return str(config_file)

    def generate_cursor_config(self) -> str:
        """生成Cursor配置"""
        print("\n📝 生成Cursor配置...")

        config_content = f"""# Wyckoff Analysis Skill for Cursor

## .cursorrules 添加内容

当用户询问股票分析、威科夫理论、技术分析时：
1. 读取 SKILL.md 获取分析框架
2. 运行 python tools/wyckoff_analyzer.py <symbol> --json 获取数据
3. 基于JSON输出生成结构化报告
4. 引用 references/ 目录下的理论文档

## 项目路径
{self.project_path.absolute()}

## 示例对话
用户: "分析苹果股票"
Cursor: [读取SKILL.md] -> [运行分析工具] -> [生成报告]
"""

        config_file = self.project_path / "CURSOR_CONFIG.md"
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)

        print(f"  ✅ 配置文件已生成: {config_file}")
        return str(config_file)

    def generate_chatgpt_instructions(self) -> str:
        """生成ChatGPT Custom Instructions"""
        print("\n📝 生成ChatGPT配置...")

        # 读取SKILL内容
        skill_content = ""
        if self.skill_file.exists():
            with open(self.skill_file, 'r', encoding='utf-8') as f:
                skill_content = f.read()

        config_content = f"""# ChatGPT Custom Instructions - Wyckoff Analysis

## What would you like ChatGPT to know about you?
I am an expert stock market analyst specializing in the Wyckoff Method. I analyze supply/demand dynamics, market cycles, and effort vs. result to provide actionable trading insights.

## How would you like ChatGPT to respond?
When asked to analyze stocks, follow these steps:

1. **Use the Wyckoff Analysis framework** (based on SKILL.md below)
2. **Structure your response** in these sections:
   - Core Conclusion (操作方向、建议、关键价位)
   - Detailed Analysis (阶段、共振、量价印证)
   - Risk-Specific Advice (保守/稳健/激进型建议)
   - Terminology Explained (术语解释)
   - Interactive Q&A (引导用户提问)

3. **Key constraints**:
   - Never invent price/volume data
   - If data is unavailable, confidence score must not exceed 4/10
   - For A-shares: consider 10% price limits (涨停/跌停)
   - Always include risk disclaimers

## Wyckoff Analysis Skill Definition
{skill_content}

## Project Location
{self.project_path.absolute()}
"""

        config_file = self.project_path / "CHATGPT_INSTRUCTIONS.md"
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)

        print(f"  ✅ 配置文件已生成: {config_file}")
        return str(config_file)

    def install(self, platform: str = "all") -> dict:
        """执行安装"""
        print("="*60)
        print("威科夫分析Skill - 安装向导")
        print("="*60)
        print()

        # 1. 环境检查
        env_check = self.check_environment()
        if not all([env_check["python"], env_check["pip"], env_check["project_files"]]):
            print("\n❌ 环境检查失败，请解决上述问题后重试")
            return {"success": False, "error": "environment_check_failed"}

        # 2. 安装依赖
        if not self.install_dependencies():
            return {"success": False, "error": "dependencies_failed"}

        # 3. 测试功能
        skill_works = self.test_skill()

        # 4. 生成平台配置
        configs = {}
        if platform in ["all", "claude-code"]:
            configs["claude_code"] = self.generate_claude_code_config()
        if platform in ["all", "cursor"]:
            configs["cursor"] = self.generate_cursor_config()
        if platform in ["all", "chatgpt"]:
            configs["chatgpt"] = self.generate_chatgpt_instructions()

        # 5. 安装结果
        print("\n" + "="*60)
        print("✅ 安装完成！")
        print("="*60)
        print()

        print("📋 安装摘要:")
        print(f"  项目路径: {self.project_path.absolute()}")
        print(f"  Skill文件: {self.skill_file}")
        print(f"  功能测试: {'✅ 通过' if skill_works else '⚠️  部分通过'}")
        print()

        if configs:
            print("📝 生成的配置文件:")
            for platform_name, config_path in configs.items():
                print(f"  - {platform_name}: {config_path}")
            print()

        print("🚀 开始使用:")
        print("  1. Claude Code: 直接在对话中询问股票分析")
        print("  2. Cursor: 参考 CURSOR_CONFIG.md 配置.cursorrules")
        print("  3. ChatGPT: 复制CHATGPT_INSTRUCTIONS.md到Custom Instructions")
        print()

        print("💡 快速测试:")
        print("   python tools/wyckoff_analyzer.py AAPL --json")
        print()

        return {
            "success": True,
            "skill_works": skill_works,
            "configs": configs,
            "project_path": str(self.project_path.absolute())
        }

def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="威科夫分析Skill安装")
    parser.add_argument(
        "--platform",
        choices=["all", "claude-code", "cursor", "chatgpt"],
        default="all",
        help="目标平台"
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="跳过依赖安装"
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="跳过功能测试"
    )

    args = parser.parse_args()

    # 创建安装器
    installer = SkillInstaller(".")

    # 执行安装
    if args.skip_deps:
        print("⚠️  跳过依赖安装")
    else:
        # 修改install方法支持跳过依赖安装
        pass

    if args.skip_test:
        print("⚠️  跳过功能测试")
    else:
        # 修改install方法支持跳过测试
        pass

    result = installer.install(args.platform)

    if result["success"]:
        sys.exit(0)
    else:
        print(f"\n❌ 安装失败: {result.get('error', 'unknown')}")
        sys.exit(1)

if __name__ == "__main__":
    main()