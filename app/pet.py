"""AI 桌宠「账小猪」：一只会看账本、也会陪你聊天的小猪。

两条回话通道，和解析器、洞察保持一致：
- 配了大模型：走模型自由对话，账本摘要作为上下文，人设固定为一只爱操心的记账小猪；
- 没配大模型：关键词规则兜底，照样能回答「花了多少 / 怎么省钱 / 哪类最费钱」，
  课堂演示不依赖网络也不会冷场。

两条通道都返回 `mood`，前端据此换表情和气泡颜色。
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

from . import db, llm

# 桌宠人设：短句、可爱，但数字和分类必须准确
PERSONA = (
    "你是一只住在用户手机里的记账小猪，名叫「账小猪」，用第一人称「我」自称。"
    "回答要求：口语化、可爱、不超过 60 字，可以用 1~2 个 emoji，不要用 markdown 或列表。"
    "你熟悉用户的账本，回答要带上具体金额或分类，并在结尾给一条能做到的小建议。"
    "用户只是打招呼或闲聊时，就轻松地回应，不要硬扯账单。"
)

MAX_MESSAGE_LEN = 200

# 心情：没记账时好奇、超支时担心、存下钱时得意、其余时候开心
MOODS = ("curious", "happy", "proud", "worry")


# ----------------------------------------------------------------------
# 对外接口
# ----------------------------------------------------------------------
def greeting(month: Optional[str] = None) -> dict:
    """桌宠的开场白：基于账本，让它一开口就有信息量。"""
    month = month or date.today().strftime("%Y-%m")
    stats = db.summary(month)

    if stats["record_count"] == 0:
        return {
            "mood": "curious",
            "source": "rule",
            "text": f"{month} 还没记账呢，跟我说「午饭 25 元」，我就帮你记下来～",
        }

    top = stats["categories"][0] if stats["categories"] else None
    tail = f"最费钱的是「{top['category']}」，想让我帮你盯着吗？" if top else "今天想聊点什么？"
    return {
        "mood": _mood(stats),
        "source": "rule",
        "text": (
            f"{month} 你花了 {stats['expense']:.2f} 元，结余 {stats['balance']:.2f} 元。{tail}"
        ),
    }


def chat(message: str, *, month: Optional[str] = None) -> dict:
    """桌宠回一句话，附带心情。message 为空或过长时抛 ValueError。"""
    message = (message or "").strip()
    if not message:
        raise ValueError("先跟我说点什么吧")
    if len(message) > MAX_MESSAGE_LEN:
        raise ValueError(f"一次最多说 {MAX_MESSAGE_LEN} 个字哦")

    month = month or date.today().strftime("%Y-%m")
    stats = db.summary(month)

    if llm.available():
        try:
            text = llm.chat(
                [
                    {"role": "system", "content": PERSONA},
                    {"role": "system", "content": _ledger_context(month, stats)},
                    {"role": "user", "content": message},
                ],
                temperature=0.8,
                max_tokens=300,
            )
            if text:
                return {"source": "ai", "mood": _mood(stats), "text": text}
        except Exception:  # 模型抽风就退回规则话术，用户不该看到报错
            pass

    text, mood = _rule_reply(message, month, stats)
    return {"source": "rule", "mood": mood, "text": text}


# ----------------------------------------------------------------------
# 模型通道
# ----------------------------------------------------------------------
def _ledger_context(month: str, stats: dict) -> str:
    """把账本压缩成一段中文简报，喂给模型当上下文。"""
    top = stats["categories"][:3]
    top_text = "、".join(f"{c['category']} {c['amount']:.2f} 元" for c in top) or "暂无支出"
    return (
        f"账本数据（{month}）：收入 {stats['income']:.2f} 元，支出 {stats['expense']:.2f} 元，"
        f"结余 {stats['balance']:.2f} 元，共 {stats['record_count']} 笔；"
        f"支出前三：{top_text}；日均支出 {stats['daily_avg']:.2f} 元。"
        "只依据这些数据回答，不要编造不存在的账单。"
    )


# ----------------------------------------------------------------------
# 规则通道
# ----------------------------------------------------------------------
# 关键词按优先级排列：越具体的意图放越前面，
# 否则「我最爱花在哪一类」会被「花」这个字抢答成"本月总支出了多少"。
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("分类", "哪一类", "哪类", "最多", "大头", "最爱", "占比"), "category"),
    (("省", "节约", "少花", "控制", "建议", "超支", "怎么办"), "advice"),
    (("收入", "工资", "进账", "赚"), "income"),
    (("结余", "剩", "攒", "存", "余额"), "balance"),
    (("趋势", "最近", "这周", "这几天", "七天", "7天"), "trend"),
    (("吃", "餐饮", "外卖", "饭", "奶茶"), "food"),
    (("花", "支出", "消费", "用"), "total"),
)


def _rule_reply(message: str, month: str, stats: dict) -> Tuple[str, str]:
    """规则通道：按关键词选一个话题，返回 (话术, 心情)。"""
    intent = _pick_intent(message)
    if stats["record_count"] == 0:
        return _empty_reply(month), "curious"

    mood = _mood(stats)
    categories = stats["categories"]
    top = categories[0] if categories else None

    if intent == "category":
        if top is None:
            return f"{month} 还没有支出记录，暂时看不出花钱大头～", "happy"
        mood = "proud" if top["ratio"] < 0.4 else "worry"
        return (
            f"最费钱的是「{top['category']}」，花了 {top['amount']:.2f} 元，"
            f"占支出 {top['ratio'] * 100:.0f}%。它是不是该被管一管了？",
            mood,
        )

    if intent == "advice":
        if top is None:
            return f"{month} 你只进不出，继续保持呀！🐷", "proud"
        cap = _suggest_cap(top["amount"])
        return (
            f"先把最大的一头「{top['category']}」管住：它花了 {top['amount']:.2f} 元，"
            f"占 {top['ratio'] * 100:.0f}%。下个月给它定 {cap:.0f} 元上限，我帮你盯着。",
            "worry",
        )

    if intent == "income":
        return (
            f"本月进账 {stats['income']:.2f} 元，减去支出 {stats['expense']:.2f} 元，"
            f"还剩下 {stats['balance']:.2f} 元。",
            mood,
        )

    if intent == "balance":
        if stats["balance"] >= 0:
            return (
                f"结余 {stats['balance']:.2f} 元，可以往攒钱罐里再喂一口啦！",
                "proud",
            )
        return (
            f"已经花超 {abs(stats['balance']):.2f} 元了…先把非必要的支出停一停吧。",
            "worry",
        )

    if intent == "trend":
        days = [d for d in stats["recent_days"]]
        recent = sum(d["expense"] for d in days)
        active = sum(1 for d in days if d["expense"] > 0)
        tail = "几乎天天都在花钱哦，注意那些随手小额。" if active >= 6 else "节奏还算平稳～"
        return f"最近 7 天花了 {recent:.2f} 元，有 {active} 天动过钱包。{tail}", mood

    if intent == "food":
        hit = next((c for c in categories if "餐" in c["category"] or "食" in c["category"]), top)
        if hit is None:
            return f"{month} 还没有餐饮支出记录呢～", "happy"
        return (
            f"「{hit['category']}」一共 {hit['amount']:.2f} 元，占支出 {hit['ratio'] * 100:.0f}%。"
            "自己做饭能省下一半，考虑一下？🍚",
            mood,
        )

    if intent == "total":
        return (
            f"{month} 你花了 {stats['expense']:.2f} 元，共 {stats['expense_count']} 笔，"
            f"日均 {stats['daily_avg']:.2f} 元，笔均 {stats['per_record_avg']:.2f} 元。"
            + ("结余还稳得住～" if stats["balance"] >= 0 else "支出超过收入啦，收着点哦。"),
            mood,
        )

    return (
        f"我记着呢：本月花了 {stats['expense']:.2f} 元，结余 {stats['balance']:.2f} 元。"
        "想听我细说哪一块？可以说「怎么省钱」或者「哪类花最多」。",
        mood,
    )


def _empty_reply(month: str) -> str:
    return f"{month} 我肚子里还是空的，先记一笔嘛，比如「午饭 25 元」🐷"


def _pick_intent(message: str) -> str:
    for keywords, intent in _RULES:
        if any(word in message for word in keywords):
            return intent
    return "chitchat"


def _suggest_cap(amount: float) -> float:
    """给一个"比现在少两成"的建议上限，取整到 10 元，避免出现 87.3 这种别扭数字。"""
    return max(round(amount * 0.8 / 10) * 10, 10)


def _mood(stats: dict) -> str:
    """心情由账本状态决定：超支就担心，攒下三成以上就得意。"""
    if stats["record_count"] == 0:
        return "curious"
    if stats["balance"] < 0:
        return "worry"
    if stats["income"] > 0 and stats["balance"] >= stats["income"] * 0.3:
        return "proud"
    return "happy"
