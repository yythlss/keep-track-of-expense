"""数据层测试：建表、CRUD、统计聚合与月份边界。"""

from __future__ import annotations

from datetime import date


def test_init_db_is_idempotent(db):
    """重复建表不应报错，也不应清空已有数据。"""
    db.add_record(type="expense", amount=10, category="餐饮")
    db.init_db()
    db.init_db()
    assert len(db.list_records()) == 1


def test_add_and_list_record(db):
    record = db.add_record(
        type="expense", amount=32, category="交通", note="打车", happened_on="2026-09-12"
    )
    assert record["id"] > 0
    assert record["amount"] == 32.0
    assert record["note"] == "打车"
    assert record["happened_on"] == "2026-09-12"
    assert record["created_at"]

    records = db.list_records()
    assert len(records) == 1
    assert records[0]["category"] == "交通"


def test_amount_is_rounded_to_two_decimals(db):
    """金额统一保留两位小数，避免浮点尾差。"""
    assert db.add_record(type="expense", amount=19.999, category="餐饮")["amount"] == 20.0
    assert db.add_record(type="expense", amount=13.5, category="餐饮")["amount"] == 13.5


def test_default_happened_on_is_today(db):
    assert db.add_record(type="expense", amount=10, category="餐饮")["happened_on"] == (
        date.today().isoformat()
    )


def test_list_records_filters(db):
    db.add_record(type="expense", amount=10, category="餐饮", happened_on="2026-09-01")
    db.add_record(type="expense", amount=20, category="交通", happened_on="2026-09-02")
    db.add_record(type="income", amount=100, category="工资", happened_on="2026-09-03")
    db.add_record(type="expense", amount=30, category="餐饮", happened_on="2026-08-31")

    assert len(db.list_records(month="2026-09")) == 3
    assert len(db.list_records(category="餐饮")) == 2
    assert len(db.list_records(type="income")) == 1
    assert len(db.list_records(month="2026-09", category="餐饮", type="expense")) == 1
    assert len(db.list_records(limit=1)) == 1


def test_list_records_sorted_by_date_desc(db):
    db.add_record(type="expense", amount=10, category="餐饮", happened_on="2026-09-01")
    db.add_record(type="expense", amount=20, category="餐饮", happened_on="2026-09-03")
    db.add_record(type="expense", amount=30, category="餐饮", happened_on="2026-09-02")

    dates = [r["happened_on"] for r in db.list_records()]
    assert dates == ["2026-09-03", "2026-09-02", "2026-09-01"]


def test_delete_record(db):
    record = db.add_record(type="expense", amount=10, category="餐饮")
    assert db.delete_record(record["id"]) is True
    assert db.delete_record(record["id"]) is False
    assert db.list_records() == []


def test_month_bounds_cross_year(db):
    """12 月的查询上界必须跨到次年 1 月，否则跨年统计会漏数据。"""
    db.add_record(type="expense", amount=99, category="其他", happened_on="2027-01-01")
    assert db.list_records(month="2026-12") == []
    assert len(db.list_records(month="2027-01")) == 1


def test_month_bounds_excludes_next_month_first_day(db):
    """半开区间 [本月1日, 下月1日)：下月 1 号的记录不能算进本月。"""
    db.add_record(type="expense", amount=50, category="其他", happened_on="2026-10-01")
    assert db.summary("2026-09")["expense"] == 0.0


def test_summary_totals_and_categories(db):
    db.add_record(type="income", amount=1000, category="工资", happened_on="2026-09-01")
    db.add_record(type="expense", amount=300, category="餐饮", happened_on="2026-09-02")
    db.add_record(type="expense", amount=100, category="交通", happened_on="2026-09-03")

    stats = db.summary("2026-09")
    assert stats["income"] == 1000.0
    assert stats["expense"] == 400.0
    assert stats["balance"] == 600.0
    assert stats["record_count"] == 3

    # 分类只统计支出，且按金额倒序
    assert [c["category"] for c in stats["categories"]] == ["餐饮", "交通"]
    assert stats["categories"][0]["amount"] == 300.0
    assert stats["categories"][0]["ratio"] == 0.75


def test_summary_balance_can_be_negative(db):
    db.add_record(type="income", amount=100, category="工资", happened_on="2026-09-01")
    db.add_record(type="expense", amount=250, category="餐饮", happened_on="2026-09-02")
    assert db.summary("2026-09")["balance"] == -150.0


def test_summary_empty_month(db):
    stats = db.summary("2026-09")
    assert stats["income"] == 0.0
    assert stats["expense"] == 0.0
    assert stats["record_count"] == 0
    assert stats["categories"] == []
    assert all(day["amount"] == 0 for day in stats["recent_days"])


def test_recent_days_returns_seven_ordered_buckets(db):
    """近 7 日趋势固定 7 条、按日期升序，缺失日期补 0（前端无需再补零）。"""
    stats = db.summary("2026-09")
    days = stats["recent_days"]
    assert len(days) == 7
    assert [d["date"] for d in days] == sorted(d["date"] for d in days)
    # 每天都要能回答"收了多少、花了多少、几笔"，所以这四个字段是必须的
    assert all({"date", "amount", "income", "expense", "balance", "count"} <= set(d) for d in days)


def test_recent_days_buckets_both_directions(db):
    """同一天的收入和支出分开统计，`amount` 仍然等于当天支出。"""
    # 先问出这个月近 7 日窗口的右边界，再往那天记账——
    # 这样无论测试在什么时候运行，日期都必定落在窗口内
    target = db.summary("2026-04")["recent_days"][-1]["date"]
    db.add_record(type="expense", amount=88, category="餐饮", happened_on=target)
    db.add_record(type="income", amount=500, category="工资", happened_on=target)

    days = {d["date"]: d for d in db.summary("2026-04")["recent_days"]}
    assert days[target]["amount"] == 88.0
    assert days[target]["expense"] == 88.0
    assert days[target]["income"] == 500.0
    assert days[target]["balance"] == 412.0
    assert days[target]["count"] == 2


def test_summary_extra_stats(db):
    """看板的细口径：日均、笔均、有支出的天数、花得最多的一天。"""
    db.add_record(type="expense", amount=100, category="餐饮", happened_on="2026-09-01")
    db.add_record(type="expense", amount=300, category="购物", happened_on="2026-09-01")
    db.add_record(type="expense", amount=80, category="交通", happened_on="2026-09-05")
    db.add_record(type="income", amount=1000, category="工资", happened_on="2026-09-10")

    stats = db.summary("2026-09")
    assert stats["expense"] == 480.0
    assert stats["expense_count"] == 3          # 收入那笔不算进笔数
    assert stats["active_days"] == 2
    assert stats["daily_avg"] == 16.0           # 480 / 30 天
    assert stats["per_record_avg"] == 160.0     # 480 / 3 笔
    assert stats["top_day"] == {"date": "2026-09-01", "amount": 400.0}


def test_summary_extra_stats_on_empty_month(db):
    """没账可记时不能除零，返回零值即可。"""
    stats = db.summary("2026-03")
    assert stats["daily_avg"] == 0.0
    assert stats["per_record_avg"] == 0.0
    assert stats["expense_count"] == 0
    assert stats["active_days"] == 0
    assert stats["top_day"] is None
