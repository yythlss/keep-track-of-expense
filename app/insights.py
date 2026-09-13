"""AI 消费洞察：先用模板兜底，有模型时再让 AI 说人话。

降级策略与解析器一致——任何时候调用都能拿到一段可读的结论。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from . import db, llm


def generate_insight(month: Optional[str] = None) -> dict:
    """生成某月消费洞察，返回 {month, text, source}。"""
    month = month or date.today().strftime("%Y-%m")
    stats = db.summary(month)

    if stats["record_count"] == 0:
        return {
            "month": month,
            "source": "rule",
            "text": f"{month} 还没有记账记录。先用一句话记一笔吧，比如「午饭 25 元」。",
        }

    if llm.available():
        try:
            return {"month": month, "source": "ai", "text": _ai_insight(stats)}
        except Exception:
            pass

    return {"month": month, "source": "rule", "text": _template_insight(stats)}


# ----------------------------------------------------------------------
# 模板版
# ----------------------------------------------------------------------
def _template_insight(stats: dict) -> str:
    lines = [
        f"{stats['month']} 共记录 {stats['record_count']} 笔，"
        f"收入 {stats['income']:.2f} 元、支出 {stats['expense']:.2f} 元，"
        f"结余 {stats['balance']:.2f} 元。"
    ]

    categories = stats["categories"]
    if categories:
        top = categories[0]
        lines.append(
            f"开销大头是「{top['category']}」{top['amount']:.2f} 元，"
            f"占总支出的 {top['ratio'] * 100:.0f}%。"
        )
        if top["ratio"] >= 0.5:
            lines.append(f"建议给「{top['category']}」设一个每月上限，先把最大的一头管住。")
        else:
            lines.append("支出结构比较分散，可以每周复盘一次，找出不必要的“小钱”。")

    active_days = sum(1 for day in stats["recent_days"] if day["amount"] > 0)
    if active_days == 0:
        lines.append("最近 7 天没有支出记录，是省钱的一周，继续保持。")
    elif active_days >= 6:
        lines.append("最近 7 天几乎天天有支出，留意“随手花”累积起来的小额开销。")

    if stats["balance"] < 0:
        lines.append("本月支出已经超过收入，建议先暂停非必要消费。")
    else:
        lines.append("总体处于可控范围，继续保持记录习惯就能看见变化。")

    return "".join(lines)


# ----------------------------------------------------------------------
# AI 版
# ----------------------------------------------------------------------
def _ai_insight(stats: dict) -> str:
    brief = {
        "月份": stats["month"],
        "收入": stats["income"],
        "支出": stats["expense"],
        "结余": stats["balance"],
        "笔数": stats["record_count"],
        "支出分类": stats["categories"][:5],
        "近7日每日支出": stats["recent_days"],
    }
    system = (
        "你是一个亲切、克制的个人理财助理。基于用户的月度账单数据，"
        "用中文写一段 100~150 字的消费洞察：先概括收支情况，再指出最值得注意的一点，"
        "最后给 1 条具体可执行的省钱建议。不要客套，不要分点罗列，不要编造数据。"
    )
    return llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(brief, ensure_ascii=False)},
        ],
        temperature=0.5,
        max_tokens=400,
    )
