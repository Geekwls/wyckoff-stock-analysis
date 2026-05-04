#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
README 声明校验脚本
检查 README.md 中的关键数量型声明是否与实际仓库状态一致
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

# Windows UTF-8 输出支持
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class RepoClaimsChecker:
    """仓库声明检查器"""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root).resolve()
        self.readme_path = self.repo_root / "README.md"
        self.errors = []
        self.warnings = []

    def count_test_files(self) -> int:
        """统计测试文件数量"""
        tests_dir = self.repo_root / "tests"
        if not tests_dir.exists():
            return 0

        test_files = list(tests_dir.glob("test_*.py"))
        return len(test_files)

    def count_test_functions(self) -> int:
        """统计测试函数数量"""
        tests_dir = self.repo_root / "tests"
        if not tests_dir.exists():
            return 0

        count = 0
        for test_file in tests_dir.glob("test_*.py"):
            try:
                with open(test_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 统计 test_ 开头的函数
                    count += len(re.findall(r'^\s*def test_\w+', content, re.MULTILINE))
            except Exception:
                pass
        return count

    def check_directory_structure(self) -> dict:
        """检查目录结构声明"""
        structure = {
            "src/wyckoff": False,
            "apps/cli": False,
            "apps/mcp": False,
            "tests": False,
            "references": False,
        }

        for key in structure.keys():
            structure[key] = (self.repo_root / key).exists()

        return structure

    def check_readme_claims(self) -> bool:
        """检查 README 中的声明"""
        print("=" * 70)
        print("README 声明校验")
        print("=" * 70)

        readme_content = self.readme_path.read_text(encoding='utf-8') if self.readme_path.exists() else ""

        # 1. 检查测试数量声明
        test_count = self.count_test_functions()
        print(f"\n[测试统计]")
        print(f"  实际测试函数数量: {test_count}")

        # 查找 README 中的测试声明
        test_claims = re.findall(r'(\d+)\+\s*个?\s*[单测|测试]', readme_content)
        if test_claims:
            claimed = int(test_claims[0])
            print(f"  README 声明: {claimed}+")
            if claimed > test_count:
                self.errors.append(f"测试数量声明过高: README 声称 {claimed}+，实际 {test_count}")
            else:
                print(f"  ✅ 测试数量声明合理")
        else:
            print(f"  ℹ️  README 未包含具体测试数量声明")

        # 2. 检查目录结构
        print(f"\n[目录结构检查]")
        structure = self.check_directory_structure()
        for dir_name, exists in structure.items():
            status = "✅" if exists else "❌"
            print(f"  {status} {dir_name}/")
            if not exists and dir_name in ["src/wyckoff", "apps/cli", "tests"]:
                self.errors.append(f"关键目录缺失: {dir_name}/")

        # 3. 检查文件路径声明
        print(f"\n[文件路径检查]")
        critical_files = [
            ("src/wyckoff/facade.py", "WyckoffAnalyzer 入口"),
            ("src/wyckoff/core/pattern_detector.py", "形态探测器"),
            ("apps/cli/main.py", "CLI 工具"),
            ("apps/mcp/server.py", "MCP 服务器"),
            ("SKILL.md", "AI Agent 技能定义"),
        ]

        for file_path, description in critical_files:
            full_path = self.repo_root / file_path
            exists = full_path.exists()
            status = "✅" if exists else "❌"
            print(f"  {status} {file_path} ({description})")

            if not exists:
                self.errors.append(f"关键文件缺失: {file_path} ({description})")

        # 4. 检查版本号
        print(f"\n[版本号检查]")
        version_match = re.search(r'v(\d+\.\d+\.\d+)', readme_content)
        if version_match:
            version = version_match.group(1)
            print(f"  README 版本: v{version}")
            print(f"  ✅ 版本号格式正确")
        else:
            self.warnings.append("README 中未找到版本号声明")

        # 打印结果
        print("\n" + "=" * 70)
        print("校验结果")
        print("=" * 70)

        if self.errors:
            print(f"\n❌ 发现 {len(self.errors)} 个错误:")
            for error in self.errors:
                print(f"  - {error}")

        if self.warnings:
            print(f"\n⚠️  发现 {len(self.warnings)} 个警告:")
            for warning in self.warnings:
                print(f"  - {warning}")

        if not self.errors and not self.warnings:
            print("\n✅ 所有检查通过！README 声明与仓库状态一致")

        return len(self.errors) == 0

    def generate_readme_snippet(self) -> str:
        """生成 README 统计片段"""
        test_count = self.count_test_functions()
        test_files = self.count_test_files()
        today = datetime.now().strftime("%Y-%m-%d")

        snippet = f"""
<!-- 自动校验统计，最后更新: {today} -->
- **测试覆盖**: {test_count} 个测试用例 ({test_files} 个测试文件)
- **架构**: 分层架构 (库层 src/wyckoff/ + 应用层 apps/)
- **最后校验**: {today}
"""
        return snippet


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="检查 README 声明与仓库状态一致性")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="仓库根目录路径"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="更新 README 中的统计信息"
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI 模式，失败时返回非零退出码"
    )

    args = parser.parse_args()

    checker = RepoClaimsChecker(args.repo_root)
    success = checker.check_readme_claims()

    if args.update:
        snippet = checker.generate_readme_snippet()
        print(f"\n[建议的 README 统计片段]")
        print(snippet)

    if args.ci and not success:
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
