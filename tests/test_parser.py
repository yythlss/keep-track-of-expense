"""解析器测试。

默认全部走**规则通道**（夹具已清空大模型环境变量），因此不依赖网络与凭证；
AI 通道用 monkeypatch 打桩单独验证降级与纠偏行为。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app import llm, parser


@pytest.fixture(autouse=True)
def _force_rule_channel(isolated_env):
    """每个用例开始前确认大模型处于不可用状态。"""
    assert llm.available() is False


# ----------------------------------------------------------------------
# 金额解析
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("午饭外卖 25 元", 25.0),
        ("昨天打车 32 块", 32.0),
        ("奶茶 13.5 元", 13.5),
        ("买书 88", 88.0),
        ("房租 ¥2000", 2000.0),
    ],
)
def test_extract_amount(text, expected):
    assert parser.parse_text(text)["amount"] == expected


def test_missing_amount_raises():
    with pytest.raises(ValueError, match="金额"):
        parser.parse_text("今天心情不错")


def test_empty_text_raises():
    with pytest.raises(ValueError):
        parser.parse_text("   ")


# ----------------------------------------------------------------------
# 日期解析
# ----------------------------------------------------------------------
def test_relative_date_today():
    assert parser.parse_text("今天午饭 25 元")["happened_on"] == date.today().isoformat()


def test_relative_date_yesterday():
    expected = (date.today() - timedelta(days=1)).isoformat()
    assert parser.parse_text("昨天打车 32 块")["happened_on"] == expected


def test_relative_date_before_yesterday():
    expected = (date.today() - timedelta(days=2)).isoformat()
    assert parser.parse_text("前天吃饭 50 元")["happened_on"] == expected


def test_no_date_word_defaults_to_today():
    assert parser.parse_text("午饭 25 元")["happened_on"] == date.today().isoformat()


def test_absolute_date_chinese_format():
    assert parser.parse_text("3月5日 买咖啡 18 元")["happened_on"] == f"{date.today().year}-03-05"


def test_absolute_date_slash_format():
    assert parser.parse_text("3/5 买咖啡 18 元")["happened_on"] == f"{date.today().year}-03-05"


def test_illegal_absolute_date_falls_back_to_today():
    """2 月 30 日不存在，应回退到今天而不是抛错。"""
    assert parser.parse_text("2月30日 吃饭 20 元")["happened_on"] == date.today().isoformat()


# ----------------------------------------------------------------------
# 类型与分类
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,category",
    [
        ("午饭外卖 25 元", "餐饮"),
        ("昨天打车 32 块", "交通"),
        ("买衣服 199 元", "购物"),
        ("电影票 45 元", "娱乐"),
        ("房租 2000 元", "居住"),
        ("买药 30 元", "医疗"),
        ("买书 88", "学习"),
    ],
)
def test_expense_category(text, category):
    result = parser.parse_text(text)
    assert result["type"] == "expense"
    assert result["category"] == category


@pytest.mark.parametrize(
    "text,category",
    [
        ("今天发工资 12000", "工资"),
        ("收到红包 200 元", "红包"),
        ("兼职收入 500 元", "兼职"),
        ("基金收益 300 元", "理财"),
        ("报销 150 元", "报销"),
    ],
)
def test_income_category(text, category):
    result = parser.parse_text(text)
    assert result["type"] == "income"
    assert result["category"] == category


def test_expense_verb_overrides_income_keyword():
    """「买了本理财书」同时命中收入词「理财」和支出语境「买」，必须判为支出。"""
    result = parser.parse_text("买了本理财书 50 元")
    assert result["type"] == "expense"
    # 「买」是泛化动词，不参与分类；分类由名词「书」决定
    assert result["category"] == "学习"


def test_unknown_category_falls_back_to_other():
    assert parser.parse_text("随便花掉 15 元")["category"] == "其他"


def test_note_is_cleaned():
    """备注应剔除金额与时间词。"""
    note = parser.parse_text("昨天打车 32 块")["note"]
    assert "32" not in note
    assert "昨天" not in note


# ----------------------------------------------------------------------
# 通道选择与降级
# ----------------------------------------------------------------------
def test_source_is_rule_without_llm():
    assert parser.parse_text("午饭 25 元")["source"] == "rule"


def test_uses_ai_result_when_valid(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: json.dumps(
            {
                "type": "expense",
                "amount": 66,
                "category": "娱乐",
                "note": "看电影",
                "happened_on": "2026-09-10",
            },
            ensure_ascii=False,
        ),
    )

    result = parser.parse_text("随便说点什么 66")
    assert result["source"] == "ai"
    assert result["category"] == "娱乐"
    assert result["happened_on"] == "2026-09-10"
    assert result["amount"] == 66.0


def test_ai_output_wrapped_in_code_fence_is_parsed(monkeypatch):
    """模型偶尔会用 ```json 包裹输出，解析器必须容忍。"""
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: '```json\n{"type":"expense","amount":18,"category":"餐饮",'
        '"note":"咖啡","happened_on":"2026-09-10"}\n```',
    )
    assert parser.parse_text("咖啡 18 元")["amount"] == 18.0


def test_ai_invalid_category_is_corrected_by_rules(monkeypatch):
    """模型给出不存在的分类时，用规则关键词纠偏，而不是直接入库。"""
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: '{"type":"expense","amount":30,"category":"不存在的分类",'
        '"note":"打车","happened_on":"2026-09-10"}',
    )

    result = parser.parse_text("打车 30 元")
    assert result["source"] == "ai"
    assert result["category"] == "交通"


def test_ai_bad_amount_falls_back_to_regex(monkeypatch):
    """模型把金额填成 0 时，用正则从原文再捞一次。"""
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: '{"type":"expense","amount":0,"category":"餐饮",'
        '"note":"午饭","happened_on":"2026-09-10"}',
    )
    assert parser.parse_text("午饭 45 元")["amount"] == 45.0


def test_non_json_output_falls_back_to_rule(monkeypatch):
    """模型输出不是 JSON 时静默降级，绝不让记账失败。"""
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "抱歉，我不太确定你在说什么")

    result = parser.parse_text("午饭 25 元")
    assert result["source"] == "rule"
    assert result["amount"] == 25.0


def test_llm_exception_falls_back_to_rule(monkeypatch):
    """模型调用抛异常（超时、鉴权失败等）时同样降级。"""
    monkeypatch.setattr(llm, "available", lambda: True)

    def _boom(*args, **kwargs):
        raise RuntimeError("网络超时")

    monkeypatch.setattr(llm, "chat", _boom)

    result = parser.parse_text("昨天打车 32 块")
    assert result["source"] == "rule"
    assert result["category"] == "交通"
