"""AI 桌宠：规则话术、心情判定、接口校验，以及模型通道的降级行为。

测试环境里没有大模型（conftest 会清空相关环境变量），所以默认走规则通道；
模型通道用 monkeypatch 打桩，验证「有模型就用模型、模型挂了也不能报错」。
"""

from __future__ import annotations

import pytest

from app import pet


def _seed(db_module) -> None:
    """一份有结余的账本：收入 5000、支出 620，结余够高，心情应该是得意的。"""
    db_module.add_record(type="income", amount=5000, category="工资", happened_on="2026-09-01")
    db_module.add_record(type="expense", amount=500, category="购物", happened_on="2026-09-02")
    db_module.add_record(type="expense", amount=120, category="餐饮", happened_on="2026-09-03")


# ----------------------------------------------------------------------
# 规则通道
# ----------------------------------------------------------------------
def test_greeting_on_empty_month_asks_for_records(db):
    data = pet.greeting("2026-09")
    assert data["mood"] == "curious"
    assert "还没记账" in data["text"]


def test_greeting_mentions_real_numbers(db):
    _seed(db)
    data = pet.greeting("2026-09")
    assert "620.00" in data["text"]
    assert "购物" in data["text"]  # 顺口点出花得最多的一类


def test_mood_is_proud_when_saving_ratio_is_healthy(db):
    _seed(db)
    # 结余 4380 元，远超收入的 30%，猪猪有理由得意
    assert pet.greeting("2026-09")["mood"] == "proud"


def test_chat_reports_total_and_averages(db):
    _seed(db)
    data = pet.chat("这个月我花了多少？", month="2026-09")
    assert data["source"] == "rule"
    assert "620.00" in data["text"]
    assert "共 3 笔" in data["text"]
    assert "笔均" in data["text"]


def test_chat_prefers_category_intent_over_total(db):
    """「我最爱花在哪一类」里同时出现"花"和"类"，不能被总额抢答。"""
    _seed(db)
    text = pet.chat("我最爱花在哪一类？", month="2026-09")["text"]
    assert "购物" in text
    assert "81%" in text  # 500 / 620


def test_chat_advice_suggests_a_cap(db):
    _seed(db)
    data = pet.chat("我该怎么省钱？", month="2026-09")
    assert data["mood"] == "worry"
    assert "购物" in data["text"]
    assert "400" in data["text"]  # 比现在少两成的建议上限


def test_chat_answers_income_and_balance(db):
    _seed(db)
    assert "5000.00" in pet.chat("这个月工资进账多少", month="2026-09")["text"]
    assert "4380.00" in pet.chat("我攒下多少了？", month="2026-09")["text"]


def test_chat_worries_when_overspent(db):
    db.add_record(type="income", amount=100, category="工资", happened_on="2026-09-01")
    db.add_record(type="expense", amount=250, category="餐饮", happened_on="2026-09-02")

    data = pet.chat("我攒下多少了？", month="2026-09")
    assert data["mood"] == "worry"
    assert "150.00" in data["text"]


def test_chat_trend_only_counts_last_seven_days(db):
    target = db.summary("2026-04")["recent_days"][-1]["date"]
    db.add_record(type="expense", amount=70, category="餐饮", happened_on=target)

    data = pet.chat("最近几天花得多吗？", month="2026-04")
    assert "70.00" in data["text"]
    assert "1 天" in data["text"]


def test_chat_chitchat_still_answers_with_numbers(db):
    """闲聊也要有信息量，不能答非所问地空转。"""
    _seed(db)
    data = pet.chat("你好呀", month="2026-09")
    assert data["source"] == "rule"
    assert "620.00" in data["text"]


def test_chat_on_empty_month_nudges_to_record(db):
    data = pet.chat("我花了多少？", month="2026-09")
    assert data["mood"] == "curious"
    assert "空的" in data["text"]


def test_chat_rejects_empty_and_overlong_message(db):
    with pytest.raises(ValueError):
        pet.chat("   ", month="2026-09")
    with pytest.raises(ValueError):
        pet.chat("花" * (pet.MAX_MESSAGE_LEN + 1), month="2026-09")


def test_chat_trims_whitespace(db):
    _seed(db)
    assert pet.chat("  我花了多少？  ", month="2026-09")["source"] == "rule"


# ----------------------------------------------------------------------
# 模型通道与降级
# ----------------------------------------------------------------------
def test_uses_model_when_available(db, monkeypatch):
    _seed(db)
    from app import llm

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: "我是账小猪，购物花太多啦！")

    data = pet.chat("帮我看看这个月", month="2026-09")
    assert data["source"] == "ai"
    assert data["text"] == "我是账小猪，购物花太多啦！"


def test_falls_back_to_rules_when_model_breaks(db, monkeypatch):
    _seed(db)
    from app import llm

    monkeypatch.setattr(llm, "available", lambda: True)

    def boom(messages, **kwargs):
        raise RuntimeError("模型挂了")

    monkeypatch.setattr(llm, "chat", boom)

    data = pet.chat("我花了多少？", month="2026-09")
    assert data["source"] == "rule"
    assert "620.00" in data["text"]


def test_ignores_blank_model_reply(db, monkeypatch):
    """模型返回空串时同样退回规则话术，别让气泡空着。"""
    _seed(db)
    from app import llm

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat", lambda messages, **kwargs: "   ")

    assert pet.chat("我花了多少？", month="2026-09")["source"] == "rule"


# ----------------------------------------------------------------------
# HTTP 接口
# ----------------------------------------------------------------------
def test_chat_endpoint_returns_text_and_mood(client):
    client.post(
        "/api/records", json={"amount": 300, "category": "餐饮", "happened_on": "2026-09-02"}
    )
    res = client.post("/api/pet/chat", json={"message": "我花了多少？", "month": "2026-09"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["source"] == "rule"
    assert "300.00" in data["text"]
    assert data["mood"] in pet.MOODS


def test_chat_endpoint_defaults_to_current_month(client):
    """不带 month 时按本月处理，不能报错。"""
    res = client.post("/api/pet/chat", json={"message": "你好"})
    assert res.status_code == 200
    assert res.get_json()["text"]


def test_chat_endpoint_rejects_empty_message(client):
    res = client.post("/api/pet/chat", json={"message": "   "})
    assert res.status_code == 400
    assert res.get_json()["error"]


def test_chat_endpoint_rejects_missing_body(client):
    assert client.post("/api/pet/chat").status_code == 400


def test_chat_endpoint_validates_month(client):
    res = client.post("/api/pet/chat", json={"message": "你好", "month": "2026/09"})
    assert res.status_code == 400


def test_greeting_endpoint(client):
    data = client.get("/api/pet/greeting?month=2026-09").get_json()
    assert data["mood"] == "curious"
    assert "2026-09" in data["text"]


def test_greeting_endpoint_validates_month(client):
    assert client.get("/api/pet/greeting?month=nope").status_code == 400
