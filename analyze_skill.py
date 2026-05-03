#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
威科夫分析Skill架构审核工具
从AI Agent Skill开发角度进行全面审核
"""

import re
import os
import json
from typing import Dict, List, Tuple
from collections import Counter

class SkillAuditor:
    """Skill架构审核器"""

    def __init__(self, project_path: str = "."):
        self.project_path = project_path
        self.skill_md_path = os.path.join(project_path, "SKILL.md")
        self.analyzer_path = os.path.join(project_path, "tools/wyckoff_analyzer.py")
        self.findings = {}

    def analyze_all(self) -> Dict:
        """执行全面审核"""
        analysis_results = {
            "skill_structure": self.analyze_skill_structure(),
            "code_implementation": self.analyze_code_implementation(),
            "user_experience": self.analyze_user_experience(),
            "platform_compatibility": self.analyze_platform_compatibility(),
            "reliability": self.analyze_reliability(),
            "documentation": self.analyze_documentation(),
            "integration": self.analyze_integration()
        }
        analysis_results["overall"] = self.calculate_overall_score(analysis_results)
        return analysis_results

    def analyze_skill_structure(self) -> Dict:
        """分析SKILL.md结构"""
        if not os.path.exists(self.skill_md_path):
            return {"error": "SKILL.md not found"}

        with open(self.skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        checks = {
            "metadata_frontmatter": bool(re.search(r'^---.*?^---', content, re.MULTILINE | re.DOTALL)),
            "thinking_mechanism": "<thinking>" in content,
            "core_procedure": "Core Operating Procedure" in content,
            "output_formatting": "Output Formatting" in content,
            "knowledge_retrieval": "Knowledge Retrieval" in content,
            "strict_rules": "Strict Rules" in content,
            "tooling_guide": "Tooling" in content,
            "anti_hallucination": any(keyword in content for keyword in ["Anti-Hallucination", "Never Invent", "不依赖幻觉"]),
            "version_info": "version:" in content.lower(),
            "description": "description:" in content.lower()
        }

        score = sum(checks.values()) / len(checks) * 100

        # 详细分析
        sections = len(re.findall(r'^#{1,3}\s+', content, re.MULTILINE))
        thinking_guidance = len(re.findall(r'<thinking>|<thinking', content))
        constraint_count = len(re.findall(r'[0-9]+\.\s+', content))

        return {
            "score": round(score, 1),
            "checks": checks,
            "details": {
                "total_sections": sections,
                "thinking_blocks": thinking_guidance,
                "constraint_rules": constraint_count,
                "word_count": len(content.split())
            }
        }

    def analyze_code_implementation(self) -> Dict:
        """分析代码实现完整性"""
        # 检查整个tools目录
        tools_path = os.path.join(self.project_path, "tools")
        if not os.path.exists(tools_path):
            return {"error": "tools directory not found"}

        # 读取所有Python文件
        all_code = ""
        for root, dirs, files in os.walk(tools_path):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            all_code += f.read() + "\n"
                    except Exception as e:
                        print(f"Warning: Could not read {file_path}: {e}")

        code = all_code

        implementations = {
            "json_output": "def generate_json" in code,
            "spring_detection": "def detect_spring" in code,
            "sos_detection": "def detect_sos" in code,
            "upthrust_detection": "def detect_upthrust" in code,
            "lps_detection": "def detect_lps" in code,
            "lpsy_detection": "def detect_lpsy" in code,
            "climax_detection": "def detect_climax" in code,
            "automatic_reaction": "def detect_automatic_reaction" in code,
            "secondary_test": "def detect_secondary_test" in code,

            "supply_demand_law": any(keyword in code.lower() for keyword in ["supply_demand", "供需定律"]),
            "effort_result_law": any(keyword in code.lower() for keyword in ["effort_result", "努力结果"]),
            "cause_effect_law": any(keyword in code.lower() for keyword in ["cause_effect", "因果定律"]),

            "batch_scanning": "def batch_scan" in code,
            "multi_timeframe": "multi_timeframe" in code.lower(),
            "relative_strength": "relative_strength" in code.lower(),
            "market_context": "market_context" in code.lower(),
            "trading_plan": "trading_plan" in code.lower()
        }

        score = sum(implementations.values()) / len(implementations) * 100

        # 代码质量指标
        function_count = len(re.findall(r'def\s+\w+\(', code))
        class_count = len(re.findall(r'class\s+\w+', code))
        docstring_count = len(re.findall(r'""".*?"""', code, re.DOTALL))
        type_hints = len(re.findall(r'->\s*\w+', code))

        return {
            "score": round(score, 1),
            "implementations": implementations,
            "code_metrics": {
                "total_functions": function_count,
                "total_classes": class_count,
                "docstring_coverage": f"{docstring_count}/{function_count}",
                "type_hints_count": type_hints,
                "lines_of_code": len(code.splitlines())
            }
        }

    def analyze_user_experience(self) -> Dict:
        """分析用户体验设计"""
        if not os.path.exists(self.skill_md_path):
            return {"error": "SKILL.md not found"}

        with open(self.skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        ux_features = {
            "clear_instructions": any(keyword in content for keyword in ["Step 1", "步骤1", "First,"]),
            "code_examples": "```" in content,
            "error_handling": "Error" in content or "error" in content,
            "output_template": "##" in content or "模板" in content,
            "interactive_qa": any(keyword in content for keyword in ["Interactive Q&A", "交互式问答", "问答"]),
            "risk_warnings": any(keyword in content for keyword in ["risk", "风险", "warning", "警告"]),
            "actionable_advice": any(keyword in content for keyword in ["action", "行动", "advice", "建议"]),
            "terminology_explanation": "术语" in content or "terminology" in content.lower()
        }

        score = sum(ux_features.values()) / len(ux_features) * 100

        return {
            "score": round(score, 1),
            "ux_features": ux_features
        }

    def analyze_platform_compatibility(self) -> Dict:
        """分析多平台兼容性"""
        if not os.path.exists(self.skill_md_path):
            return {"error": "SKILL.md not found"}

        with open(self.skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        platform_checks = {
            "cursor_compatible": "Cursor" in content or "VS Code" in content,
            "claude_code_compatible": "Claude Code" in content or "claude" in content.lower(),
            "chatgpt_compatible": "ChatGPT" in content or "GPT" in content,
            "cli_tool_support": "python tools/" in content.lower() or "命令行" in content,
            "path_independence": any(keyword in content for keyword in ["tools/", "当前目录", "working directory"]),
            "universal_instructions": any(keyword in content for keyword in ["AI Agent", "大语言模型", "LLM"])
        }

        score = sum(platform_checks.values()) / len(platform_checks) * 100

        return {
            "score": round(score, 1),
            "platform_checks": platform_checks
        }

    def analyze_reliability(self) -> Dict:
        """分析可靠性保障"""
        if not os.path.exists(self.skill_md_path):
            return {"error": "SKILL.md not found"}

        with open(self.skill_md_path, 'r', encoding='utf-8') as f:
            skill_content = f.read()

        if not os.path.exists(self.analyzer_path):
            code_content = ""
        else:
            with open(self.analyzer_path, 'r', encoding='utf-8') as f:
                code_content = f.read()

        reliability_features = {
            "data_dependency_check": any(keyword in skill_content for keyword in ["NOT rely on pure hallucination", "不依赖幻觉", "hard quantitative data"]),
            "validation_mechanism": any(keyword in skill_content for keyword in ["verify", "验证", "check", "检查"]),
            "error_recovery": any(keyword in skill_content for keyword in ["fail", "失败", "error", "错误"]),
            "quality_indicators": any(keyword in skill_content for keyword in ["confidence", "置信度", "score", "评分"]),
            "risk_warnings": any(keyword in skill_content for keyword in ["risk", "风险", "warning", "警告", "disclaimer", "免责"]),
            "data_source_requirements": "data" in skill_content.lower() and "source" in skill_content.lower()
        }

        score = sum(reliability_features.values()) / len(reliability_features) * 100

        # 代码可靠性检查
        code_reliability = {
            "exception_handling": "try:" in code_content and "except" in code_content,
            "custom_exceptions": "WyckoffError" in code_content or "class.*Error" in code_content,
            "logging": "logging" in code_content or "logger" in code_content,
            "input_validation": any(keyword in code_content for keyword in ["validate", "检查", "verify"])
        }

        return {
            "score": round(score, 1),
            "skill_reliability": reliability_features,
            "code_reliability": code_reliability
        }

    def analyze_documentation(self) -> Dict:
        """分析文档支持"""
        doc_files = {
            "theory_full": "references/wyckoff-theory-full.md",
            "china_guide": "references/china-market-guide.md",
            "common_pitfalls": "references/common-pitfalls.md",
            "learning_path": "references/learning-path.md",
            "quick_reference": "references/quick-reference.md",
            "chart_examples": "references/chart-examples",
            "strategies": "references/market-strategies"
        }

        docs_status = {}
        total_words = 0

        for doc_name, doc_path in doc_files.items():
            if os.path.isdir(doc_path):
                # 目录，检查文件数量
                try:
                    files = [f for f in os.listdir(doc_path) if f.endswith('.md')]
                    docs_status[doc_name] = {
                        "exists": True,
                        "type": "directory",
                        "file_count": len(files)
                    }
                except PermissionError:
                    docs_status[doc_name] = {"exists": False, "error": "Permission denied"}
            elif os.path.exists(doc_path):
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                word_count = len(content.split())
                total_words += word_count
                docs_status[doc_name] = {
                    "exists": True,
                    "words": word_count
                }
            else:
                docs_status[doc_name] = {"exists": False}

        # 计算文档覆盖率
        coverage = sum(1 for status in docs_status.values() if status.get("exists", False)) / len(docs_status) * 100

        return {
            "documentation_coverage": round(coverage, 1),
            "total_documentation_words": total_words,
            "documents_status": docs_status
        }

    def analyze_integration(self) -> Dict:
        """分析集成就绪度"""
        if not os.path.exists(self.analyzer_path):
            return {"error": "wyckoff_analyzer.py not found"}

        with open(self.analyzer_path, 'r', encoding='utf-8') as f:
            code = f.read()

        integration_checks = {
            "cli_tool_available": os.path.exists(self.analyzer_path),
            "json_output": "def generate_json" in code,
            "command_line_args": "argparse" in code or "sys.argv" in code or "__main__" in code,
            "error_handling": "except" in code,
            "logging_system": "logging" in code or "logger" in code,
            "config_management": "WyckoffConfig" in code,
            "main_entry_point": "if __name__" in code,
            "batch_operations": "batch" in code.lower()
        }

        score = sum(integration_checks.values()) / len(integration_checks) * 100

        return {
            "score": round(score, 1),
            "integration_checks": integration_checks
        }

    def calculate_overall_score(self, analysis_results: Dict = None) -> Dict:
        """计算总体评分"""
        if analysis_results is None:
            analysis_results = {
                "skill_structure": self.analyze_skill_structure(),
                "code_implementation": self.analyze_code_implementation(),
                "user_experience": self.analyze_user_experience(),
                "platform_compatibility": self.analyze_platform_compatibility(),
                "reliability": self.analyze_reliability(),
                "documentation": self.analyze_documentation(),
                "integration": self.analyze_integration()
            }

        scores = {
            "skill_structure": analysis_results["skill_structure"].get("score", 0),
            "code_implementation": analysis_results["code_implementation"].get("score", 0),
            "user_experience": analysis_results["user_experience"].get("score", 0),
            "platform_compatibility": analysis_results["platform_compatibility"].get("score", 0),
            "reliability": analysis_results["reliability"].get("score", 0),
            "documentation": analysis_results["documentation"].get("documentation_coverage", 0),
            "integration": analysis_results["integration"].get("score", 0)
        }

        total_score = sum(scores.values()) / len(scores)

        # 评级
        if total_score >= 90:
            grade = "A+ (卓越)"
            stars = "★★★★★"
        elif total_score >= 80:
            grade = "A (优秀)"
            stars = "★★★★☆"
        elif total_score >= 70:
            grade = "B (良好)"
            stars = "★★★☆☆"
        elif total_score >= 60:
            grade = "C (合格)"
            stars = "★★☆☆☆"
        else:
            grade = "D (需改进)"
            stars = "★☆☆☆☆"

        return {
            "total_score": round(total_score, 1),
            "individual_scores": scores,
            "grade": grade,
            "stars": stars,
            "recommendation": self.get_recommendation(total_score)
        }

    def get_recommendation(self, score: float) -> str:
        """根据分数给出建议"""
        if score >= 90:
            return "Skill设计优秀，可直接用于生产环境"
        elif score >= 80:
            return "Skill设计良好，建议完善文档和测试后使用"
        elif score >= 70:
            return "Skill基本可用，需要改进关键功能"
        elif score >= 60:
            return "Skill存在明显问题，需要重大改进"
        else:
            return "Skill不适合当前使用，建议重新设计"

    def print_report(self):
        """打印审核报告"""
        analysis = self.analyze_all()
        overall = analysis["overall"]

        print("=" * 70)
        print("威科夫分析Skill - 架构全面审核报告")
        print("=" * 70)
        print()

        # 各维度评分
        for aspect, score in overall["individual_scores"].items():
            stars = "★" * int(score / 20)
            print(f"[{aspect.replace('_', ' ').title()}] {score:.0f}% {stars}")

        print()
        print("=" * 70)
        print(f"总体评分: {overall['total_score']}/100")
        print(f"等级: {overall['grade']} {overall['stars']}")
        print(f"建议: {overall['recommendation']}")
        print("=" * 70)

        # 详细分析
        print("\n详细分析结果:")
        print("-" * 70)

        for category, data in analysis.items():
            if category == "overall":
                continue

            print(f"\n{category.replace('_', ' ').title()}:")

            if "score" in data:
                print(f"  Score: {data['score']}%")

            if "checks" in data:
                for check, passed in data["checks"].items():
                    status = "[OK]" if passed else "[MISSING]"
                    print(f"    {status} {check}")

            if "implementations" in data:
                for feature, implemented in data["implementations"].items():
                    status = "[OK]" if implemented else "[MISSING]"
                    print(f"    {status} {feature}")

if __name__ == "__main__":
    auditor = SkillAuditor(".")
    auditor.print_report()
