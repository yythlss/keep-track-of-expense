"""日历视图 + 个性化设置测试。

两条核心不变量：
    日历 = 当月 records 的逐日汇总（整月每天都返回，空白日补 0）
    个性化设置 = 键值对，部分更新，不认识 / 不合法的值一律拒收
"""

from __future__ import annotations

import re

MONTH_LENGTHS = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


# ----------------------------------------------------------------------
# 数据层 · 日历
# ----------------------------------------------------------------------
def test_calendar_covers_every_day_of_month(db):
    days = db.calendar("2026-09")["days"]
    assert len(days) == 30
    assert days[0]["date"] == "2026-09-01"
    assert days[-1]["date"] == "2026-09-30"
    assert [day["day"] for day in days] == list(range(1, 31))


def test_calendar_leading_aligns_first_day_to_monday(db):
    """2026-09-01 是周二，周一开头的日历要在前面留 1 格。"""
    assert db.calendar("2026-09")["leading"] == 1


def test_calendar_leading_is_zero_when_month_starts_on_monday(db):
    assert db.calendar("2026-06")["leading"] == 0  # 2026-06-01 是周一


def test_calendar_february_2028_has_29_days(db):
    """闰年 2 月必须是 29 天，否则日历最后一天会画不出来。"""
    assert len(db.calendar("2028-02")["days"]) == 29
    assert len(db.calendar("2026-02")["days"]) == 28


def test_calendar_sums_same_day_records(db):
    db.add_record(type="expense", amount=10, category="餐饮", happened_on="2026-09-05")
    db.add_record(type="expense", amount=5.5, category="交通", happened_on="2026-09-05")
    db.add_record(type="income", amount=300, category="工资", happened_on="2026-09-05")

    day = db.calendar("2026-09")["days"][4]
    assert day["date"] == "2026-09-05"
    assert day["expense"] == 15.5
    assert day["income"] == 300.0
    assert day["balance"] == 284.5
    assert day["count"] == 3


def test_calendar_empty_days_are_zeroed(db):
    days = db.calendar("2026-09")["days"]
    assert all(day["count"] == 0 for day in days)
    assert all(day["expense"] == 0.0 and day["income"] == 0.0 for day in days)


def test_calendar_totals_and_peaks(db):
    db.add_record(type="expense", amount=10, category="餐饮", happened_on="2026-09-01")
    db.add_record(type="expense", amount=120, category="购物", happened_on="2026-09-02")
    db.add_record(type="income", amount=800, category="工资", happened_on="2026-09-03")

    data = db.calendar("2026-09")
    assert data["expense"] == 130.0
    assert data["income"] == 800.0
    assert data["balance"] == 670.0
    # 峰值给前端配色阶用，必须是"单日最大"而不是总和
    assert data["max_expense"] == 120.0
    assert data["max_income"] == 800.0


def test_calendar_ignores_records_from_other_months(db):
    db.add_record(type="expense", amount=99, category="餐饮", happened_on="2026-08-31")
    db.add_record(type="expense", amount=99, category="餐饮", happened_on="2026-10-01")

    data = db.calendar("2026-09")
    assert data["expense"] == 0.0
    assert all(day["count"] == 0 for day in data["days"])


def test_calendar_ignores_vault_deposits(db):
    """金库存钱是单独一条账，不能污染日历（否则等于重复计账）。"""
    vault = db.create_vault(name="旅行基金", goal=1000)
    db.add_deposit(vault_id=vault["id"], amount=200)
    db.add_record(type="expense", amount=20, category="餐饮")

    assert db.calendar()["expense"] == 20.0


def test_month_lengths_match_real_calendar(db):
    """逐月核对天数，确保跨月边界没有 off-by-one。"""
    for month, length in MONTH_LENGTHS.items():
        assert len(db.calendar(f"2026-{month:02d}")["days"]) == length, month


# ----------------------------------------------------------------------
# 接口 · 日历
# ----------------------------------------------------------------------
def test_calendar_api_defaults_to_current_month(client):
    from datetime import date

    response = client.get("/api/calendar")
    assert response.status_code == 200
    assert response.get_json()["month"] == date.today().strftime("%Y-%m")


def test_calendar_api_returns_requested_month(client):
    client.post("/api/records", json={"type": "expense", "amount": 30, "category": "餐饮", "happened_on": "2026-09-09"})

    data = client.get("/api/calendar?month=2026-09").get_json()
    assert data["month"] == "2026-09"
    assert data["days"][8]["expense"] == 30.0


def test_calendar_api_rejects_bad_month(client):
    assert client.get("/api/calendar?month=2026-9").status_code == 400
    assert client.get("/api/calendar?month=2026/09").status_code == 400


# ----------------------------------------------------------------------
# 接口 · 按日查询账单
# ----------------------------------------------------------------------
def test_records_api_filters_by_date(client):
    client.post("/api/records", json={"type": "expense", "amount": 10, "category": "餐饮", "happened_on": "2026-09-09"})
    client.post("/api/records", json={"type": "expense", "amount": 20, "category": "交通", "happened_on": "2026-09-10"})

    data = client.get("/api/records?date=2026-09-10").get_json()
    assert data["count"] == 1
    assert data["records"][0]["amount"] == 20.0


def test_records_api_rejects_bad_date(client):
    assert client.get("/api/records?date=2026-9-1").status_code == 400


# ----------------------------------------------------------------------
# 接口 · 个性化设置
# ----------------------------------------------------------------------
def test_settings_api_returns_defaults(client):
    settings = client.get("/api/settings").get_json()["settings"]
    assert settings["avatar"] == "🐷"
    assert settings["nickname"] == ""
    assert settings["bg_preset"] == "cream"
    assert settings["bg_image"] == ""


def test_settings_api_partial_update_keeps_other_fields(client):
    client.put("/api/settings", json={"nickname": "小明"})
    settings = client.put("/api/settings", json={"bg_preset": "mint"}).get_json()["settings"]

    assert settings["nickname"] == "小明"  # 上一次的改动不能被覆盖
    assert settings["bg_preset"] == "mint"
    assert settings["avatar"] == "🐷"


def test_settings_api_persists_avatar_emoji(client):
    client.put("/api/settings", json={"avatar": "🦊"})
    assert client.get("/api/settings").get_json()["settings"]["avatar"] == "🦊"


def test_settings_api_accepts_image_data_url(client):
    image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
    settings = client.put("/api/settings", json={"avatar": image, "bg_image": image}).get_json()["settings"]
    assert settings["avatar"] == image
    assert settings["bg_image"] == image


def test_settings_api_rejects_non_image_data_url(client):
    assert client.put("/api/settings", json={"avatar": "data:text/html;base64,PHNjcmlwdD4="}).status_code == 400
    assert client.put("/api/settings", json={"bg_image": "https://example.com/a.png"}).status_code == 400


def test_settings_api_rejects_long_plain_avatar(client):
    """头像只允许 emoji 或图片，一段普通文字应当被拒。"""
    assert client.put("/api/settings", json={"avatar": "this is not an avatar"}).status_code == 400


def test_settings_api_rejects_unknown_bg_preset(client):
    assert client.put("/api/settings", json={"bg_preset": "rainbow"}).status_code == 400


def test_settings_api_truncates_long_nickname(client):
    settings = client.put("/api/settings", json={"nickname": "一" * 20}).get_json()["settings"]
    assert len(settings["nickname"]) == 12


def test_settings_api_empty_avatar_falls_back_to_default(client):
    client.put("/api/settings", json={"avatar": "🦊"})
    settings = client.put("/api/settings", json={"avatar": ""}).get_json()["settings"]
    assert settings["avatar"] == "🐷"


def test_settings_api_ignores_unknown_keys(client):
    """多余字段直接忽略，不允许往偏好表里塞任意键。"""
    settings = client.put("/api/settings", json={"evil": "1", "nickname": "阿宝"}).get_json()["settings"]
    assert "evil" not in settings
    assert settings["nickname"] == "阿宝"


def test_settings_api_rejects_overlong_image(client):
    """超出长度上限的图片要拒收，避免数据库被超大 base64 撑爆。"""
    huge = "data:image/png;base64," + "A" * 400_001
    assert client.put("/api/settings", json={"avatar": huge}).status_code == 400


def test_settings_avatar_whitelist_matches_frontend(client):
    """后端只认这几种图片格式，前端也要按同一份白名单提示用户。"""
    from app.routes import _is_image_data_url

    for mime in ("png", "jpeg", "jpg", "webp", "gif"):
        assert _is_image_data_url(f"data:image/{mime};base64,AAAA")
    assert not _is_image_data_url("data:image/svg+xml;base64,AAAA")


def test_bg_presets_have_no_duplicates():
    from app.db import BG_PRESETS

    assert len(BG_PRESETS) == len(set(BG_PRESETS))
    assert all(re.fullmatch(r"[a-z]+", preset) for preset in BG_PRESETS)
