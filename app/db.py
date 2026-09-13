"""SQLite 数据层：建表、增删查与统计聚合。

设计要点：
- 零外部依赖（Python 标准库 `sqlite3`），单文件数据库，方便容器挂 volume 持久化；
- 数据库路径由环境变量 `DB_PATH` 决定（每次读取，便于测试注入），
  默认落在 `<项目根>/data/money.db`，目录不存在时自动创建。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 允许的分类（同时也是前端下拉选项与 AI 的输出约束）
EXPENSE_CATEGORIES = ["餐饮", "交通", "购物", "娱乐", "居住", "医疗", "学习", "人情", "其他"]
INCOME_CATEGORIES = ["工资", "奖金", "兼职", "红包", "理财", "报销", "其他"]

# 新建金库时的默认装饰（前端也可自行指定）
VAULT_ICONS = ["🏦", "🐷", "🎯", "✈️", "🏠", "🚗", "🎓", "💍", "🛡️", "🧳"]
VAULT_COLORS = ["#ffa94d", "#4dabf7", "#f783ac", "#9775fa", "#38d9a9", "#ffd43b"]

# 背景预设（前端按同名 key 渲染渐变，后端只负责校验取值合法）
BG_PRESETS = ["cream", "mint", "sakura", "sky", "latte", "dusk"]

# 界面偏好默认值，用户可逐项覆盖
DEFAULT_SETTINGS = {
    "nickname": "",
    "avatar": "🐷",          # emoji 或 data:image/... 的 base64 图片
    "bg_preset": BG_PRESETS[0],
    "bg_image": "",          # 自定义背景图（data URL），有值时优先于预设
}

# 各字段长度上限：图片类字段用长度兜底，避免超大 base64 把数据库撑爆
SETTINGS_MAX_LEN = {
    "nickname": 12,
    "avatar": 400_000,       # ≈ 300KB 图片
    "bg_preset": 16,
    "bg_image": 1_500_000,   # ≈ 1.1MB 图片
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT    NOT NULL CHECK (type IN ('expense', 'income')),
    amount      REAL    NOT NULL CHECK (amount >= 0),
    category    TEXT    NOT NULL,
    note        TEXT    NOT NULL DEFAULT '',
    happened_on TEXT    NOT NULL,          -- YYYY-MM-DD
    created_at  TEXT    NOT NULL           -- ISO8601
);
CREATE INDEX IF NOT EXISTS idx_records_date ON records (happened_on);
CREATE INDEX IF NOT EXISTS idx_records_category ON records (category);

-- 金库：一个金库 = 一个攒钱目标（旅行基金、应急备用金、换电脑…）
CREATE TABLE IF NOT EXISTS vaults (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    icon        TEXT    NOT NULL DEFAULT '🏦',
    goal        REAL    NOT NULL DEFAULT 0 CHECK (goal >= 0),  -- 0 表示不设目标
    color       TEXT    NOT NULL DEFAULT '#ffa94d',
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);

-- 存钱记录：每次"往金库里塞一笔钱"都是一条流水，只增不改，保证可追溯
CREATE TABLE IF NOT EXISTS vault_deposits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id    INTEGER NOT NULL REFERENCES vaults (id),
    amount      REAL    NOT NULL CHECK (amount > 0),
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deposits_vault ON vault_deposits (vault_id);

-- 界面偏好（头像 / 昵称 / 背景）：键值对随库持久化，换设备也能带走
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


# ----------------------------------------------------------------------
# 连接与初始化
# ----------------------------------------------------------------------
def db_path() -> str:
    """当前数据库文件路径。"""
    path = os.environ.get("DB_PATH") or os.path.join(PROJECT_ROOT, "data", "money.db")
    return os.path.abspath(path)


def _connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表（幂等）。"""
    with _connect() as conn:
        conn.executescript(SCHEMA)


# ----------------------------------------------------------------------
# 增删查
# ----------------------------------------------------------------------
def add_record(
    *,
    type: str,
    amount: float,
    category: str,
    note: str = "",
    happened_on: Optional[str] = None,
) -> dict:
    """写入一条账单，返回落库后的完整记录。"""
    happened_on = happened_on or date.today().isoformat()
    created_at = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO records (type, amount, category, note, happened_on, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (type, round(float(amount), 2), category, note or "", happened_on, created_at),
        )
        new_id = cur.lastrowid
        row = conn.execute("SELECT * FROM records WHERE id = ?", (new_id,)).fetchone()
    return _row_to_dict(row)


def list_records(
    *,
    month: Optional[str] = None,
    on: Optional[str] = None,
    category: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """按条件查询账单，按日期倒序。`on` 用于精确取某一天的流水（日历点选）。"""
    sql = "SELECT * FROM records WHERE 1 = 1"
    params: list = []
    if month:
        start, end = _month_bounds(month)
        sql += " AND happened_on >= ? AND happened_on < ?"
        params += [start, end]
    if on:
        sql += " AND happened_on = ?"
        params.append(on)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if type in ("expense", "income"):
        sql += " AND type = ?"
        params.append(type)
    sql += " ORDER BY happened_on DESC, id DESC LIMIT ?"
    params.append(int(limit))

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def delete_record(record_id: int) -> bool:
    """删除一条账单，返回是否删掉了东西。"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    return cur.rowcount > 0


# ----------------------------------------------------------------------
# 金库（攒钱罐）
# ----------------------------------------------------------------------
def list_vaults() -> list[dict]:
    """所有金库 + 已存金额 / 存钱次数 / 最近一次存钱时间，新建的排前面。"""
    with _connect() as conn:
        rows = conn.execute(_VAULT_SQL + " GROUP BY v.id ORDER BY v.id DESC").fetchall()
    return [_vault_to_dict(r) for r in rows]


def get_vault(vault_id: int) -> Optional[dict]:
    """单个金库详情，不存在返回 None。"""
    with _connect() as conn:
        row = conn.execute(_VAULT_SQL + " AND v.id = ? GROUP BY v.id", (vault_id,)).fetchone()
    return _vault_to_dict(row) if row else None


def create_vault(
    *,
    name: str,
    goal: float = 0.0,
    icon: str = "🏦",
    color: str = "#ffa94d",
    note: str = "",
) -> dict:
    """新建一个金库并返回它。"""
    created_at = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO vaults (name, icon, goal, color, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, icon, round(float(goal), 2), color, note or "", created_at),
        )
        new_id = cur.lastrowid
    return get_vault(new_id)


def delete_vault(vault_id: int) -> bool:
    """删除金库及其全部存钱记录（显式删子表，不依赖外键级联开关）。"""
    with _connect() as conn:
        conn.execute("DELETE FROM vault_deposits WHERE vault_id = ?", (vault_id,))
        cur = conn.execute("DELETE FROM vaults WHERE id = ?", (vault_id,))
    return cur.rowcount > 0


def add_deposit(*, vault_id: int, amount: float, note: str = "") -> Optional[dict]:
    """往金库存一笔钱，返回更新后的金库；金库不存在返回 None。"""
    created_at = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if exists is None:
            return None
        conn.execute(
            "INSERT INTO vault_deposits (vault_id, amount, note, created_at) VALUES (?, ?, ?, ?)",
            (vault_id, round(float(amount), 2), note or "", created_at),
        )
    return get_vault(vault_id)


def list_deposits(vault_id: int, limit: int = 20) -> list[dict]:
    """某个金库的存钱流水，最近的排前面。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM vault_deposits WHERE vault_id = ?"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (vault_id, int(limit)),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "vault_id": r["vault_id"],
            "amount": round(r["amount"], 2),
            "note": r["note"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ----------------------------------------------------------------------
# 统计聚合
# ----------------------------------------------------------------------
def summary(month: Optional[str] = None) -> dict:
    """某个月的收支统计：总额、分类占比、近 7 日趋势。"""
    month = month or date.today().strftime("%Y-%m")
    start, end = _month_bounds(month)

    with _connect() as conn:
        rows = conn.execute(
            "SELECT type, amount, category, happened_on FROM records"
            " WHERE happened_on >= ? AND happened_on < ?",
            (start, end),
        ).fetchall()

    income = sum(r["amount"] for r in rows if r["type"] == "income")
    expense = sum(r["amount"] for r in rows if r["type"] == "expense")

    by_category: dict[str, float] = {}
    for r in rows:
        if r["type"] != "expense":
            continue
        by_category[r["category"]] = by_category.get(r["category"], 0.0) + r["amount"]

    categories = sorted(
        (
            {
                "category": name,
                "amount": round(amount, 2),
                "ratio": round(amount / expense, 4) if expense else 0.0,
            }
            for name, amount in by_category.items()
        ),
        key=lambda item: item["amount"],
        reverse=True,
    )

    return {
        "month": month,
        "income": round(income, 2),
        "expense": round(expense, 2),
        "balance": round(income - expense, 2),
        "record_count": len(rows),
        "categories": categories,
        "recent_days": _recent_days(rows, end),
        **_extra_stats(rows, start, end, expense),
    }


def _extra_stats(rows, start: str, end: str, expense: float) -> dict:
    """看板用的细口径：日均、笔均、有支出的天数、花得最多的一天。

    这些数字单独算比让前端拿原始流水自己推更省事，也让「看板」不只是一个总数。
    """
    days_in_month = (date.fromisoformat(end) - date.fromisoformat(start)).days
    expense_rows = [r for r in rows if r["type"] == "expense"]

    by_day: dict[str, float] = {}
    for r in expense_rows:
        by_day[r["happened_on"]] = by_day.get(r["happened_on"], 0.0) + r["amount"]

    top_date, top_amount = max(by_day.items(), key=lambda kv: kv[1]) if by_day else ("", 0.0)

    return {
        "daily_avg": round(expense / days_in_month, 2) if days_in_month else 0.0,
        "per_record_avg": round(expense / len(expense_rows), 2) if expense_rows else 0.0,
        "expense_count": len(expense_rows),
        "active_days": len(by_day),
        "top_day": {"date": top_date, "amount": round(top_amount, 2)} if by_day else None,
    }


# ----------------------------------------------------------------------
# 界面偏好（头像 / 昵称 / 背景）
# ----------------------------------------------------------------------
def get_settings() -> dict:
    """读取界面偏好，缺省项用默认值补齐，保证前端永远拿到完整结构。"""
    with _connect() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    stored = {row["key"]: row["value"] for row in rows}
    return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}


def save_settings(patch: dict) -> dict:
    """部分更新界面偏好：只覆盖传入的键，返回合并后的完整偏好。

    不认识的键直接忽略；超长内容抛 `ValueError`，由路由层转成 400。
    """
    clean: dict[str, str] = {}
    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS:
            continue
        text = "" if value is None else str(value)
        if len(text) > SETTINGS_MAX_LEN[key]:
            raise ValueError(f"{key} 超出长度上限")
        clean[key] = text

    if clean:
        now = datetime.now().isoformat(timespec="seconds")
        with _connect() as conn:
            conn.executemany(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                [(key, value, now) for key, value in clean.items()],
            )
    return get_settings()


# ----------------------------------------------------------------------
# 日历视图
# ----------------------------------------------------------------------
def calendar(month: Optional[str] = None) -> dict:
    """某月逐日收支，供日历视图使用。

    返回整月每一天（含没有记录的空白日）并从周一开始排列，
    前端只需按顺序画格子，不用自己算日历排版。
    """
    month = month or date.today().strftime("%Y-%m")
    start, end = _month_bounds(month)

    with _connect() as conn:
        rows = conn.execute(
            "SELECT happened_on, type, SUM(amount) AS total, COUNT(*) AS count"
            "  FROM records WHERE happened_on >= ? AND happened_on < ?"
            " GROUP BY happened_on, type",
            (start, end),
        ).fetchall()

    buckets: dict[str, dict] = {}
    for row in rows:
        bucket = buckets.setdefault(row["happened_on"], {"income": 0.0, "expense": 0.0, "count": 0})
        bucket[row["type"]] = round(row["total"], 2)
        bucket["count"] += row["count"]

    first = date.fromisoformat(start)
    today = date.today().isoformat()
    days = []
    for offset in range((date.fromisoformat(end) - first).days):
        current = first + timedelta(days=offset)
        key = current.isoformat()
        bucket = buckets.get(key, {"income": 0.0, "expense": 0.0, "count": 0})
        income, expense = bucket["income"], bucket["expense"]
        days.append(
            {
                "date": key,
                "day": current.day,
                "is_today": key == today,
                "is_weekend": current.weekday() >= 5,
                "income": income,
                "expense": expense,
                "balance": round(income - expense, 2),
                "count": bucket["count"],
            }
        )

    income_total = round(sum(day["income"] for day in days), 2)
    expense_total = round(sum(day["expense"] for day in days), 2)
    return {
        "month": month,
        "leading": first.weekday(),  # 月首之前要留白的格子数（周一是 0）
        "days": days,
        "income": income_total,
        "expense": expense_total,
        "balance": round(income_total - expense_total, 2),
        # 给前端配色阶用：金额越大，格子颜色越深
        "max_expense": round(max((day["expense"] for day in days), default=0.0), 2),
        "max_income": round(max((day["income"] for day in days), default=0.0), 2),
    }


# ----------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------
# 金库聚合：一个金库配一条 LEFT JOIN 汇总，避免 N+1 查询
_VAULT_SQL = (
    "SELECT v.*,"
    "       COALESCE(SUM(d.amount), 0) AS saved,"
    "       COUNT(d.id) AS deposit_count,"
    "       MAX(d.created_at) AS last_deposit_at"
    "  FROM vaults v LEFT JOIN vault_deposits d ON d.vault_id = v.id"
    " WHERE 1 = 1"
)


def _vault_to_dict(row: sqlite3.Row) -> dict:
    saved = round(row["saved"] or 0.0, 2)
    goal = round(row["goal"] or 0.0, 2)
    return {
        "id": row["id"],
        "name": row["name"],
        "icon": row["icon"],
        "goal": goal,
        "color": row["color"],
        "note": row["note"],
        "created_at": row["created_at"],
        "saved": saved,
        "deposit_count": row["deposit_count"],
        "last_deposit_at": row["last_deposit_at"],
        "progress": round(saved / goal, 4) if goal > 0 else 0.0,
        "achieved": bool(goal > 0 and saved >= goal),
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "amount": round(row["amount"], 2),
        "category": row["category"],
        "note": row["note"],
        "happened_on": row["happened_on"],
        "created_at": row["created_at"],
    }


def _month_bounds(month: str) -> tuple[str, str]:
    """把 `YYYY-MM` 转成半开区间 [本月第一天, 下月第一天)。"""
    year, mon = (int(part) for part in month.split("-")[:2])
    first = date(year, mon, 1)
    nxt = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return first.isoformat(), nxt.isoformat()


def _recent_days(rows, end_exclusive: str, days: int = 7) -> list[dict]:
    """统计最近 `days` 天的每日收支与笔数（不超出今天）。

    每天都同时给出收入和支出：前端点某根柱子时，要能立刻说出
    "这天收了多少、花了多少、结余多少"，而不是只知道支出。
    `amount` 保留为当天支出，兼容既有调用方。
    """
    end_date = datetime.strptime(end_exclusive, "%Y-%m-%d").date() - timedelta(days=1)
    today = date.today()
    if end_date > today:
        end_date = today
    start_date = end_date - timedelta(days=days - 1)

    buckets = {
        (start_date + timedelta(days=i)).isoformat(): {"income": 0.0, "expense": 0.0, "count": 0}
        for i in range(days)
    }
    for r in rows:
        bucket = buckets.get(r["happened_on"])
        if bucket is None:
            continue
        bucket[r["type"]] += r["amount"]
        bucket["count"] += 1

    return [
        {
            "date": day,
            "amount": round(bucket["expense"], 2),
            "expense": round(bucket["expense"], 2),
            "income": round(bucket["income"], 2),
            "balance": round(bucket["income"] - bucket["expense"], 2),
            "count": bucket["count"],
        }
        for day, bucket in buckets.items()
    ]
