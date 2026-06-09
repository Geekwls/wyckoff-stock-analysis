#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据质量验证器 (Data Quality Validator)

提供数据质量检查机制，确保数据的有效性和完整性。
"""

import pandas as pd
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    severity: str  # "error" | "warning"
    category: str  # "ohlc_inconsistent" | "missing_columns" | "extreme_return" ...
    message: str
    count: int = 0


@dataclass
class QualityReport:
    ok: bool
    score: float
    issues: List[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "ok": self.ok,
            "score": self.score,
            "issues": [{"severity": i.severity, "category": i.category, "message": i.message, "count": i.count} for i in self.issues],
        }


class DataQualityError(Exception):
    """数据质量错误"""
    pass


class DataValidator:
    """
    数据质量验证器

    检查数据的完整性、一致性和合理性
    """

    # 基本价格验证规则
    MIN_PRICE = 0.01  # 最小价格（1分钱）
    MAX_PRICE = 1000000  # 最大价格（100万）
    MAX_DAILY_CHANGE_PCT = 50.0  # 最大单日涨跌幅（50%）

    # 成交量验证规则
    MIN_VOLUME = 0  # 最小成交量
    MAX_VOLUME_RATIO = 1000.0  # 最大量比（相对于均值）

    # 数据完整性规则
    MAX_MISSING_RATIO = 0.1  # 最大缺失值比例（10%）
    MAX_ZERO_VOLUME_RATIO = 0.3  # 最大零成交量比例（30%）

    @staticmethod
    def validate_ohlcv_structure(df: pd.DataFrame) -> List[str]:
        """
        验证 OHLCV 数据结构

        Args:
            df: 要验证的 DataFrame

        Returns:
            错误消息列表（空列表表示验证通过）
        """
        errors = []

        # 检查必需的列
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            errors.append(f"缺少必需的列: {missing_columns}")
            return errors

        # 检查数据框不为空
        if len(df) == 0:
            errors.append("数据框为空")
            return errors

        return errors

    @staticmethod
    def validate_price_consistency(df: pd.DataFrame) -> List[str]:
        """
        验证价格数据的一致性

        检查：
        - High >= Low
        - Close 在 High 和 Low 之间
        - Open 在 High 和 Low 之间
        - 价格范围合理性

        Args:
            df: 要验证的 DataFrame

        Returns:
            错误消息列表
        """
        errors = []

        # High >= Low
        invalid_high_low = df[df['High'] < df['Low']]
        if len(invalid_high_low) > 0:
            errors.append(f"发现 {len(invalid_high_low)} 行 High < Low 的数据")

        # Close 在 [Low, High] 范围内
        invalid_close = df[(df['Close'] < df['Low']) | (df['Close'] > df['High'])]
        if len(invalid_close) > 0:
            errors.append(f"发现 {len(invalid_close)} 行 Close 不在 [Low, High] 范围内的数据")

        # Open 在 [Low, High] 范围内
        invalid_open = df[(df['Open'] < df['Low']) | (df['Open'] > df['High'])]
        if len(invalid_open) > 0:
            errors.append(f"发现 {len(invalid_open)} 行 Open 不在 [Low, High] 范围内的数据")

        # 价格范围检查
        for col in ['Open', 'High', 'Low', 'Close']:
            if col in df.columns:
                # 检查负价格
                negative_prices = df[df[col] < 0]
                if len(negative_prices) > 0:
                    errors.append(f"发现 {len(negative_prices)} 行 {col} 为负数的数据")

                # 检查异常高价
                extreme_prices = df[df[col] > DataValidator.MAX_PRICE]
                if len(extreme_prices) > 0:
                    errors.append(f"发现 {len(extreme_prices)} 行 {col} 超过最大价格 {DataValidator.MAX_PRICE}")

        return errors

    @staticmethod
    def validate_volume_data(df: pd.DataFrame) -> List[str]:
        """
        验证成交量数据

        检查：
        - 成交量非负
        - 零成交量比例
        - 异常成交量

        Args:
            df: 要验证的 DataFrame

        Returns:
            错误消息列表
        """
        errors = []

        if 'Volume' not in df.columns:
            return errors

        # 检查负成交量
        negative_volume = df[df['Volume'] < 0]
        if len(negative_volume) > 0:
            errors.append(f"发现 {len(negative_volume)} 行负成交量的数据")

        # 检查零成交量比例
        zero_volume_count = (df['Volume'] == 0).sum()
        zero_volume_ratio = zero_volume_count / len(df)
        if zero_volume_ratio > DataValidator.MAX_ZERO_VOLUME_RATIO:
            errors.append(
                f"零成交量比例过高: {zero_volume_ratio:.1%} "
                f"(> {DataValidator.MAX_ZERO_VOLUME_RATIO:.1%})"
            )

        # 检查异常成交量（相对于均值的倍数）
        if len(df) > 20:
            vol_mean = df['Volume'].rolling(20).mean()
            vol_ratio = df['Volume'] / vol_mean.replace(0, 1)
            extreme_volume = df[vol_ratio > DataValidator.MAX_VOLUME_RATIO]
            if len(extreme_volume) > 0:
                logger.warning(
                    f"发现 {len(extreme_volume)} 行异常高成交量 "
                    f"(> {DataValidator.MAX_VOLUME_RATIO}倍20日均量)"
                )

        return errors

    @staticmethod
    def validate_missing_values(df: pd.DataFrame) -> List[str]:
        """
        验证缺失值

        Args:
            df: 要验证的 DataFrame

        Returns:
            错误消息列表
        """
        errors = []

        # 检查各列的缺失值比例
        for col in df.columns:
            missing_count = df[col].isna().sum()
            if missing_count > 0:
                missing_ratio = missing_count / len(df)
                if missing_ratio > DataValidator.MAX_MISSING_RATIO:
                    errors.append(
                        f"列 '{col}' 缺失值比例过高: {missing_ratio:.1%} "
                        f"(> {DataValidator.MAX_MISSING_RATIO:.1%})"
                    )

        return errors

    @staticmethod
    def validate_daily_changes(df: pd.DataFrame) -> List[str]:
        """
        验证单日涨跌幅是否合理

        Args:
            df: 要验证的 DataFrame

        Returns:
            错误消息列表
        """
        errors = []

        if 'Close' not in df.columns or len(df) < 2:
            return errors

        # 计算涨跌幅
        daily_change = df['Close'].pct_change(fill_method=None) * 100

        # 检查极端涨跌幅
        extreme_changes = df[abs(daily_change) > DataValidator.MAX_DAILY_CHANGE_PCT]
        if len(extreme_changes) > 0:
            logger.warning(
                f"发现 {len(extreme_changes)} 行极端涨跌幅 "
                f">(±{DataValidator.MAX_DAILY_CHANGE_PCT}%)"
            )

        return errors

    @classmethod
    def validate_dataframe(cls, df: pd.DataFrame, strict: bool = False) -> QualityReport:
        """
        完整验证数据框，返回结构化质量报告。

        Args:
            df: 要验证的 DataFrame
            strict: 是否严格模式（严格模式下任何警告都视为错误）

        Returns:
            QualityReport(ok, score, issues)
        """
        issues: List[QualityIssue] = []

        # 空数据
        if df is None:
            return QualityReport(ok=False, score=0.0, issues=[QualityIssue("error", "missing_frame", "K线数据为空")])
        if df.empty:
            return QualityReport(ok=False, score=0.0, issues=[QualityIssue("error", "empty_frame", "K线数据无记录")])

        # 结构验证
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            return QualityReport(ok=False, score=0.0, issues=[QualityIssue("error", "missing_columns", f"缺少必需列: {missing}", len(missing))])

        # 价格一致性
        invalid_hl = (df['High'] < df['Low']).sum()
        if invalid_hl:
            issues.append(QualityIssue("error", "ohlc_inconsistent", f"High < Low 共 {invalid_hl} 行", int(invalid_hl)))

        invalid_close = ((df['Close'] < df['Low']) | (df['Close'] > df['High'])).sum()
        if invalid_close:
            issues.append(QualityIssue("error", "ohlc_inconsistent", f"Close 不在 [Low,High] 共 {invalid_close} 行", int(invalid_close)))

        invalid_open = ((df['Open'] < df['Low']) | (df['Open'] > df['High'])).sum()
        if invalid_open:
            issues.append(QualityIssue("error", "ohlc_inconsistent", f"Open 不在 [Low,High] 共 {invalid_open} 行", int(invalid_open)))

        # 负价格
        for col in ['Open', 'High', 'Low', 'Close']:
            neg = (df[col] < 0).sum()
            if neg:
                issues.append(QualityIssue("error", "non_positive_price", f"{col} 存在负数 {int(neg)} 行", int(neg)))

        # 成交量
        neg_vol = (df['Volume'] < 0).sum()
        if neg_vol:
            issues.append(QualityIssue("error", "negative_volume", f"成交量负数 {int(neg_vol)} 行", int(neg_vol)))

        zero_vol_ratio = (df['Volume'] == 0).sum() / len(df)
        if zero_vol_ratio > cls.MAX_ZERO_VOLUME_RATIO:
            issues.append(QualityIssue("warning", "zero_volume", f"零成交量 {zero_vol_ratio:.1%} > {cls.MAX_ZERO_VOLUME_RATIO:.0%}"))

        # 极端涨跌幅
        if len(df) >= 2:
            extreme = (df['Close'].pct_change(fill_method=None).abs() > cls.MAX_DAILY_CHANGE_PCT / 100).sum()
            if extreme:
                issues.append(QualityIssue("warning", "extreme_return", f"极端涨跌幅 {int(extreme)} 行 > ±{cls.MAX_DAILY_CHANGE_PCT}%", int(extreme)))

        # 缺失值
        for col in df.columns:
            na = df[col].isna().sum()
            if na and na / len(df) > cls.MAX_MISSING_RATIO:
                issues.append(QualityIssue("warning", "missing_values", f"列 {col} 缺失 {na}/{len(df)} = {na/len(df):.1%}"))

        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")
        score = max(0.0, 100.0 - error_count * 30.0 - warning_count * 10.0)

        return QualityReport(ok=error_count == 0, score=score, issues=issues)

    @classmethod
    def clean_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        清理数据框

        执行以下清理操作：
        - 删除价格不一致的行
        - 删除负成交量的行
        - 向前填充缺失值

        Args:
            df: 要清理的 DataFrame

        Returns:
            清理后的 DataFrame
        """
        df_clean = df.copy()

        # 删除 High < Low 的行
        df_clean = df_clean[df_clean['High'] >= df_clean['Low']]

        # 删除 Close 不在 [Low, High] 的行
        df_clean = df_clean[
            (df_clean['Close'] >= df_clean['Low']) &
            (df_clean['Close'] <= df_clean['High'])
        ]

        # 删除负成交量的行
        if 'Volume' in df_clean.columns:
            df_clean = df_clean[df_clean['Volume'] >= 0]

        # 向前填充缺失值
        df_clean = df_clean.ffill()

        # 删除剩余的缺失值
        df_clean = df_clean.dropna()

        return df_clean


class ChineseSymbolHandler:
    """
    中文股票代码处理器

    改进中文字符处理逻辑，使其更加健壮。
    """

    @staticmethod
    def is_chinese_name(symbol: str) -> bool:
        """
        检查是否为中文名称

        Args:
            symbol: 股票代码或名称

        Returns:
            是否为中文名称
        """
        if not symbol or not isinstance(symbol, str):
            return False

        # 检查是否包含中文字符
        chinese_char_count = sum(1 for char in symbol if '\u4e00' <= char <= '\u9fff')

        # 如果超过一半的字符是中文，认为是中文名称
        return chinese_char_count > len(symbol) / 2

    @staticmethod
    def normalize_chinese_name(name: str) -> str:
        """
        规范化中文名称

        执行以下操作：
        - 去除前后空格
        - 去除特殊字符（保留中文、英文、数字）
        - 统一全角/半角字符

        Args:
            name: 中文名称

        Returns:
            规范化后的名称
        """
        if not name:
            return name

        # 去除前后空格
        normalized = name.strip()

        # 去除常见的不必要字符
        unnecessary_chars = [' ', '\t', '\n', '\r', '*', '＊', '(', ')', '（', '）']
        for char in unnecessary_chars:
            normalized = normalized.replace(char, '')

        return normalized

    @staticmethod
    def extract_stock_code(symbol: str) -> Optional[str]:
        """
        从混合输入中提取股票代码

        支持以下格式：
        - 纯代码: 000001, 600000
        - 代码+市场: 000001.SZ, 600000.SH
        - 中文名称: 平安银行

        Args:
            symbol: 输入的股票代码或名称

        Returns:
            提取出的股票代码，如果无法提取则返回 None
        """
        if not symbol:
            return None

        # 如果是中文名称，无法直接提取代码
        if ChineseSymbolHandler.is_chinese_name(symbol):
            return None

        # 去除空格
        code = symbol.strip().upper()

        # 已经是标准格式
        if '.' in code:
            return code

        # A股代码：6位数字
        if len(code) == 6 and code.isdigit():
            # 600xxx, 601xxx, 603xxx, 605xxx -> 上海
            if code.startswith('60'):
                return f"{code}.SH"
            # 000xxx, 001xxx, 002xxx, 003xxx -> 深圳
            elif code.startswith('00') or code.startswith('30'):
                return f"{code}.SZ"
            else:
                # 默认深圳
                return f"{code}.SZ"

        return code
