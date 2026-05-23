"""策略决策审计日志 — 记录压分、降仓、观望等规则的触发明细，便于回测与人工复盘。"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class DecisionCategory(str, Enum):
    SCORE_PENALTY = "score_penalty"
    SCORE_CAP = "score_cap"
    POSITION_REDUCE = "position_reduce"
    WATCH = "watch"


class StrategyDecisionAuditLog:
    """Collect structured strategy decision events for a single analysis run."""

    def __init__(self) -> None:
        self._symbol: Optional[str] = None
        self._started_at: Optional[str] = None
        self._entries: List[Dict[str, Any]] = []

    def begin(self, symbol: Optional[str] = None) -> None:
        self._symbol = symbol
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._entries = []

    @property
    def entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def _append(
        self,
        *,
        rule_id: str,
        category: DecisionCategory,
        message: str,
        stage: str,
        delta: Optional[float] = None,
        score_before: Optional[int] = None,
        score_after: Optional[int] = None,
        cap_value: Optional[int] = None,
        position_before: Optional[str] = None,
        position_after: Optional[str] = None,
        position_factor: Optional[float] = None,
        direction_before: Optional[str] = None,
        direction_after: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._started_at is None:
            self.begin()

        self._entries.append({
            'rule_id': rule_id,
            'category': category.value,
            'message': message,
            'stage': stage,
            'delta': delta,
            'score_before': score_before,
            'score_after': score_after,
            'cap_value': cap_value,
            'position_before': position_before,
            'position_after': position_after,
            'position_factor': position_factor,
            'direction_before': direction_before,
            'direction_after': direction_after,
            'context': context or {},
        })

    def record_score_penalty(
        self,
        rule_id: str,
        delta: float,
        score_before: int,
        score_after: int,
        message: str,
        *,
        stage: str = 'scoring',
        **context: Any,
    ) -> None:
        self._append(
            rule_id=rule_id,
            category=DecisionCategory.SCORE_PENALTY,
            message=message,
            stage=stage,
            delta=delta,
            score_before=score_before,
            score_after=score_after,
            context=context or None,
        )

    def record_score_cap(
        self,
        rule_id: str,
        cap_value: int,
        score_before: int,
        score_after: int,
        message: str,
        *,
        stage: str = 'scoring',
        **context: Any,
    ) -> None:
        self._append(
            rule_id=rule_id,
            category=DecisionCategory.SCORE_CAP,
            message=message,
            stage=stage,
            cap_value=cap_value,
            score_before=score_before,
            score_after=score_after,
            context=context or None,
        )

    def record_position_reduce(
        self,
        rule_id: str,
        position_before: str,
        position_after: str,
        message: str,
        *,
        position_factor: Optional[float] = None,
        stage: str = 'trading_plan',
        **context: Any,
    ) -> None:
        self._append(
            rule_id=rule_id,
            category=DecisionCategory.POSITION_REDUCE,
            message=message,
            stage=stage,
            position_before=position_before,
            position_after=position_after,
            position_factor=position_factor,
            context=context or None,
        )

    def record_watch(
        self,
        rule_id: str,
        message: str,
        *,
        direction_before: Optional[str] = None,
        direction_after: str = '观望',
        stage: str = 'trading_plan',
        **context: Any,
    ) -> None:
        self._append(
            rule_id=rule_id,
            category=DecisionCategory.WATCH,
            message=message,
            stage=stage,
            direction_before=direction_before,
            direction_after=direction_after,
            context=context or None,
        )

    def summary(self) -> Dict[str, Any]:
        by_category: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        rule_ids: List[str] = []
        for entry in self._entries:
            cat = entry['category']
            stage = entry['stage']
            by_category[cat] = by_category.get(cat, 0) + 1
            by_stage[stage] = by_stage.get(stage, 0) + 1
            rule_ids.append(entry['rule_id'])
        return {
            'total_events': len(self._entries),
            'by_category': by_category,
            'by_stage': by_stage,
            'rule_ids': rule_ids,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self._symbol,
            'started_at': self._started_at,
            'summary': self.summary(),
            'entries': self.entries,
        }


_CATEGORY_LABELS = {
    DecisionCategory.SCORE_PENALTY.value: '压分',
    DecisionCategory.SCORE_CAP.value: '评分上限',
    DecisionCategory.POSITION_REDUCE.value: '降仓',
    DecisionCategory.WATCH.value: '观望',
}

_STAGE_LABELS = {
    'scoring': '评分',
    'trading_plan': '交易计划',
    'risk_advice': '风险建议',
}


def format_audit_markdown(audit: Optional[Dict[str, Any]]) -> str:
    """Render strategy decision audit log as a Markdown-friendly report section."""
    if not audit:
        return ''

    entries = audit.get('entries') or []
    if not entries:
        return ''

    summary = audit.get('summary') or {}
    by_category = summary.get('by_category') or {}
    symbol = audit.get('symbol') or '—'
    started_at = audit.get('started_at') or '—'

    lines = [
        '',
        '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━',
        '',
        '【策略决策审计日志】',
        f'   标的: {symbol} | 分析时间 (UTC): {started_at}',
        f'   事件总数: {summary.get("total_events", len(entries))}',
        (
            '   分类汇总: '
            f'压分 {by_category.get(DecisionCategory.SCORE_PENALTY.value, 0)} | '
            f'评分上限 {by_category.get(DecisionCategory.SCORE_CAP.value, 0)} | '
            f'降仓 {by_category.get(DecisionCategory.POSITION_REDUCE.value, 0)} | '
            f'观望 {by_category.get(DecisionCategory.WATCH.value, 0)}'
        ),
        '',
    ]

    for index, entry in enumerate(entries, start=1):
        category = entry.get('category', '')
        stage = entry.get('stage', '')
        rule_id = entry.get('rule_id', '')
        message = entry.get('message', '')
        cat_label = _CATEGORY_LABELS.get(category, category)
        stage_label = _STAGE_LABELS.get(stage, stage)

        detail_parts = []
        if entry.get('delta') is not None:
            detail_parts.append(f"Δ{entry['delta']:+.0f}")
        if entry.get('score_before') is not None and entry.get('score_after') is not None:
            detail_parts.append(f"得分 {entry['score_before']}→{entry['score_after']}")
        if entry.get('cap_value') is not None:
            detail_parts.append(f"上限 {entry['cap_value']}")
        if entry.get('position_before') and entry.get('position_after'):
            detail_parts.append(f"仓位 {entry['position_before']}→{entry['position_after']}")
        if entry.get('direction_before') or entry.get('direction_after'):
            before = entry.get('direction_before') or '—'
            after = entry.get('direction_after') or '—'
            detail_parts.append(f"方向 {before}→{after}")

        detail = ' | '.join(detail_parts)
        lines.append(f"   {index}. [{cat_label}/{stage_label}] `{rule_id}`")
        lines.append(f"      {message}")
        if detail:
            lines.append(f"      ({detail})")

    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    lines.append('')
    return '\n'.join(lines)


def iter_audit_jsonl_records(audit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten one audit run into per-event records for JSONL backtest export."""
    if not audit:
        return []
    base = {
        'symbol': audit.get('symbol'),
        'started_at': audit.get('started_at'),
        'audit_event_count': (audit.get('summary') or {}).get('total_events', 0),
    }
    return [{**base, **entry} for entry in (audit.get('entries') or [])]


def write_audit_jsonl(audit: Optional[Dict[str, Any]], path: str, *, append: bool = True) -> int:
    """Write flattened audit records to JSONL. Returns number of lines written."""
    import json
    from pathlib import Path

    records = iter_audit_jsonl_records(audit)
    if not records:
        return 0

    mode = 'a' if append else 'w'
    outfile = Path(path)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    with outfile.open(mode, encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write('\n')
    return len(records)


def audit_summary_fields(audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact audit fields for screener rows and batch backtest exports."""
    if not audit:
        return {
            'audit_event_count': 0,
            'audit_penalty_count': 0,
            'audit_cap_count': 0,
            'audit_position_reduce_count': 0,
            'audit_watch_count': 0,
            'audit_rule_ids': [],
        }
    summary = audit.get('summary') or {}
    by_category = summary.get('by_category') or {}
    return {
        'audit_event_count': summary.get('total_events', 0),
        'audit_penalty_count': by_category.get(DecisionCategory.SCORE_PENALTY.value, 0),
        'audit_cap_count': by_category.get(DecisionCategory.SCORE_CAP.value, 0),
        'audit_position_reduce_count': by_category.get(DecisionCategory.POSITION_REDUCE.value, 0),
        'audit_watch_count': by_category.get(DecisionCategory.WATCH.value, 0),
        'audit_rule_ids': summary.get('rule_ids') or [],
    }
