"""一句话记账：把「昨天打车 32 块」这类自然语言解析成结构化账单。

双通道策略，保证「没网也能用」：
1. **AI 通道**：配置了大模型时，让它输出严格 JSON（理解力更强）；
2. **规则通道**：无大模型 / 模型返回异常时，用正则 + 关键词表兜底。

两条通道返回同一种结构，前端完全无感知。
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Optional

from . import llm

# ----------------------------------------------------------------------
# 关键词表（既是规则依据，也是给 AI 的分类候选）
# ----------------------------------------------------------------------
EXPENSE_KEYWORDS: dict[str, list[str]] = {
    "餐饮": [
        "早餐", "午餐", "晚餐", "午饭", "晚饭", "宵夜", "夜宵", "外卖", "食堂", "餐厅",
        "吃饭", "聚餐", "火锅", "烧烤", "咖啡", "奶茶", "零食", "水果", "下午茶", "喝了", "吃了",
    ],
    "交通": [
        "打车", "滴滴", "地铁", "公交", "高铁", "火车", "机票", "飞机", "加油", "停车",
        "共享单车", "单车", "车费", "路费", "油费", "过路费",
    ],
    # 注意：这里刻意不收录「买 / 买了」这类泛化动词——它们会把「买书」「买药」
    # 误判成购物。动词只作为「这笔是支出」的倾向线索（见 EXPENSE_HINTS），
    # 分类判定完全交给名词。
    "购物": [
        "购物", "淘宝", "京东", "拼多多", "衣服", "鞋", "包", "化妆品",
        "日用品", "超市", "快递", "数码",
    ],
    "娱乐": ["电影", "游戏", "唱歌", "ktv", "旅游", "演唱会", "门票", "酒吧", "剧本杀", "密室"],
    "居住": ["房租", "水电", "物业", "燃气", "宽带", "话费", "网费", "住宿", "酒店", "家具"],
    "医疗": ["看病", "医院", "药", "体检", "挂号", "门诊", "牙医", "疫苗"],
    "学习": ["书", "课程", "学费", "培训", "考试", "文具", "会员", "订阅", "网课"],
    "人情": ["礼物", "随礼", "请客", "份子钱", "孝敬"],
}

INCOME_KEYWORDS: dict[str, list[str]] = {
    "工资": ["工资", "薪水", "月薪", "发薪", "发了工资"],
    "奖金": ["奖金", "年终奖", "提成", "补贴"],
    "兼职": ["兼职", "外快", "副业", "接单", "稿费"],
    "红包": ["红包", "压岁钱"],
    "理财": ["理财", "利息", "基金", "股票", "分红", "收益"],
    "报销": ["报销", "退款", "返现", "退税"],
}

INCOME_HINTS = ["收入", "进账", "入账", "收到", "赚了", "赚到", "发了"]
EXPENSE_HINTS = ["花了", "支出", "付了", "买", "缴", "消费", "付钱"]

_AMOUNT_WITH_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块钱|块|人民币|rmb|RMB|¥|￥)")
_AMOUNT_ANY = re.compile(r"(\d+(?:\.\d+)?)")
_DATE_CN = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_DATE_MD = re.compile(r"(?<!\d)(\d{1,2})\s*[/-]\s*(\d{1,2})(?!\d)")


# ----------------------------------------------------------------------
# 对外统一入口
# ----------------------------------------------------------------------
def parse_text(text: str) -> dict:
    """解析一句话，返回 {type, amount, category, note, happened_on, source}。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("记账内容不能为空")

    if llm.available():
        try:
            data = _ai_parse(text)
            data["source"] = "ai"
            return data
        except Exception:
            pass  # 任何异常都静默降级，绝不让记账失败

    data = _rule_parse(text)
    data["source"] = "rule"
    return data


# ----------------------------------------------------------------------
# AI 通道
# ----------------------------------------------------------------------
def _ai_parse(text: str) -> dict:
    today = date.today().isoformat()
    system = (
        "你是一个中文记账助手，负责把用户的口语化描述整理成结构化账单。\n"
        f"今天是 {today}（用于解析“昨天/前天”等相对日期）。\n"
        "只输出一个 JSON 对象，不要输出任何解释、不要使用代码块。字段如下：\n"
        '{"type": "expense|income", "amount": 数字, "category": 字符串, '
        '"note": 简短备注(≤12字), "happened_on": "YYYY-MM-DD"}\n'
        f"支出分类只能是：{'、'.join(EXPENSE_KEYWORDS.keys())}、其他\n"
        f"收入分类只能是：{'、'.join(INCOME_KEYWORDS.keys())}、其他\n"
        "若金额缺失，amount 填 0。"
    )
    raw = llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        max_tokens=256,
    )
    data = _extract_json(raw)
    return _normalize(data, fallback_text=text)


def _extract_json(raw: str) -> dict:
    """从模型输出里抠出 JSON（容忍 ```json 代码块等噪音）。"""
    content = raw.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型输出中找不到 JSON")
    return json.loads(content[start : end + 1])


def _normalize(data: dict, *, fallback_text: str) -> dict:
    """校验并规整模型输出，避免脏数据入库。"""
    type_ = data.get("type") if data.get("type") in ("expense", "income") else "expense"

    try:
        amount = float(data.get("amount") or 0)
    except (TypeError, ValueError):
        raise ValueError("模型返回的金额不是数字")
    if amount <= 0:
        # 金额没解析出来时，再退回正则捞一次
        amount = _extract_amount(fallback_text) or 0
    if amount <= 0:
        raise ValueError("没有识别到金额，请补充金额（例如：午饭 25 元）")

    allowed = INCOME_KEYWORDS.keys() if type_ == "income" else EXPENSE_KEYWORDS.keys()
    category = str(data.get("category") or "").strip()
    if category not in list(allowed) + ["其他"]:
        category = _match_category(fallback_text, type_) or "其他"

    note = str(data.get("note") or "").strip()[:20] or fallback_text[:20]
    happened_on = _clean_date(data.get("happened_on")) or date.today().isoformat()

    return {
        "type": type_,
        "amount": round(amount, 2),
        "category": category,
        "note": note,
        "happened_on": happened_on,
    }


# ----------------------------------------------------------------------
# 规则通道
# ----------------------------------------------------------------------
def _rule_parse(text: str) -> dict:
    amount = _extract_amount(text)
    if not amount:
        raise ValueError("没有识别到金额，请补充金额（例如：午饭 25 元）")

    type_ = _detect_type(text)
    category = _match_category(text, type_) or "其他"

    return {
        "type": type_,
        "amount": round(amount, 2),
        "category": category,
        "note": _clean_note(text),
        "happened_on": _extract_date(text),
    }


def _extract_amount(text: str) -> Optional[float]:
    match = _AMOUNT_WITH_UNIT.search(text)
    if not match:
        match = _AMOUNT_ANY.search(text)
    return float(match.group(1)) if match else None


def _detect_type(text: str) -> str:
    if any(word in text for word in INCOME_HINTS):
        return "income"
    for words in INCOME_KEYWORDS.values():
        if any(word in text for word in words):
            # 仅当句子不是在描述“花钱买”时，才判定为收入
            if not any(word in text for word in EXPENSE_HINTS):
                return "income"
    return "expense"


def _match_category(text: str, type_: str) -> Optional[str]:
    mapping = INCOME_KEYWORDS if type_ == "income" else EXPENSE_KEYWORDS
    for category, words in mapping.items():
        if any(word in text for word in words):
            return category
    return None


def _extract_date(text: str) -> str:
    today = date.today()
    if "大前天" in text:
        return (today - timedelta(days=3)).isoformat()
    if "前天" in text:
        return (today - timedelta(days=2)).isoformat()
    if "昨天" in text or "昨日" in text:
        return (today - timedelta(days=1)).isoformat()
    if "今天" in text or "今日" in text or "刚才" in text:
        return today.isoformat()

    match = _DATE_CN.search(text)
    if match:
        return _safe_date(today.year, int(match.group(1)), int(match.group(2))) or today.isoformat()

    match = _DATE_MD.search(text)
    if match:
        return _safe_date(today.year, int(match.group(1)), int(match.group(2))) or today.isoformat()

    return today.isoformat()


def _safe_date(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _clean_date(value) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _clean_note(text: str) -> str:
    """去掉金额与描述性词，留下更像“备注”的片段。"""
    note = _AMOUNT_WITH_UNIT.sub("", text)
    note = note.replace("花了", "").replace("付了", "").replace("收到", "")
    note = re.sub(r"(今天|昨天|前天|大前天|今日|昨日|刚才)", "", note)
    note = re.sub(r"[，。,.!！?？、\s]+", " ", note).strip()
    return (note or text)[:20]
