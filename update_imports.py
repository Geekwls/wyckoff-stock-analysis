#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新导入路径脚本
将 tools/ 的导入更新为 src/wyckoff/ 的导入
"""

import os
import re

def update_imports_in_file(filepath):
    """更新单个文件的导入路径"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 替换规则
    replacements = [
        # tools.xxx -> src.wyckoff.xxx
        (r'from tools\.([^\s]+)', r'from src.wyckoff.\1'),
        (r'import tools\.([^\s]+)', r'import src.wyckoff.\1'),

        # .config.settings -> .config.settings (保持不变，因为已经在 src/wyckoff/ 下)
        # .core.xxx -> .core.xxx (保持不变)

        # ..config.settings -> ..config.settings (保持不变)
    ]

    # 对于 src/wyckoff/ 下的文件，不需要修改
    # 因为它们使用的是相对导入，这是正确的

    # 对于应用层文件（apps/），需要更新
    if 'apps/' in filepath:
        # tools.xxx -> src.wyckoff.xxx
        content = re.sub(r'from tools\.([^\s]+)', r'from src.wyckoff.\1', content)
        content = re.sub(r'import tools\.([^\s]+)', r'import src.wyckoff.\1', content)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    return False

def main():
    """主函数"""
    project_root = os.path.dirname(os.path.abspath(__file__))

    # 更新 apps/ 下的文件
    apps_dir = os.path.join(project_root, 'apps')
    for root, dirs, files in os.walk(apps_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                if update_imports_in_file(filepath):
                    print(f"Updated: {filepath}")

    # 更新 tests/ 下的文件
    tests_dir = os.path.join(project_root, 'tests')
    if os.path.exists(tests_dir):
        for root, dirs, files in os.walk(tests_dir):
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    if update_imports_in_file(filepath):
                        print(f"Updated: {filepath}")

    print("\n导入路径更新完成！")

if __name__ == "__main__":
    main()
