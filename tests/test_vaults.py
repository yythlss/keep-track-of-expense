"""金库（攒钱罐）测试：数据层聚合 + 5 个接口的主流程与边界。

金库的核心不变量：
    已存金额 = 该金库全部存钱记录之和（只增不减，可追溯）
    攒钱进度 = 已存 / 目标（未设目标时恒为 0，且不判定为"已攒满"）
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# 数据层
# ----------------------------------------------------------------------
def test_new_vault_starts_empty(db):
    vault = db.create_vault(name="旅行基金", goal=1000)
    assert vault["saved"] == 0.0
    assert vault["deposit_count"] == 0
    assert vault["progress"] == 0.0
    assert vault["achieved"] is False
    assert vault["last_deposit_at"] is None


def test_deposits_accumulate(db):
    vault = db.create_vault(name="旅行基金", goal=1000)
    db.add_deposit(vault_id=vault["id"], amount=300)
    updated = db.add_deposit(vault_id=vault["id"], amount=200.5)

    assert updated["saved"] == 500.5
    assert updated["deposit_count"] == 2
    assert updated["progress"] == 0.5005
    assert updated["last_deposit_at"]


def test_deposit_to_missing_vault_returns_none(db):
    assert db.add_deposit(vault_id=9999, amount=10) is None


def test_progress_without_goal_stays_zero(db):
    """不设目标时进度恒为 0，且永远不算"已攒满"——否则前端进度条会满格误导。"""
    vault = db.create_vault(name="零钱罐", goal=0)
    updated = db.add_deposit(vault_id=vault["id"], amount=88)

    assert updated["saved"] == 88.0
    assert updated["progress"] == 0.0
    assert updated["achieved"] is False


def test_achieved_when_goal_reached(db):
    vault = db.create_vault(name="换电脑", goal=500)
    db.add_deposit(vault_id=vault["id"], amount=300)
    updated = db.add_deposit(vault_id=vault["id"], amount=300)

    assert updated["achieved"] is True
    # progress 不封顶，前端据此展示"超出目标多少"
    assert updated["progress"] == 1.2


def test_vaults_are_isolated_from_each_other(db):
    travel = db.create_vault(name="旅行基金", goal=1000)
    laptop = db.create_vault(name="换电脑", goal=5000)
    db.add_deposit(vault_id=travel["id"], amount=120)

    vaults = {v["name"]: v for v in db.list_vaults()}
    assert vaults["旅行基金"]["saved"] == 120.0
    assert vaults["换电脑"]["saved"] == 0.0


def test_delete_vault_removes_its_deposits(db):
    """删金库必须连带删掉存钱记录，否则会留下永远查不到的孤儿数据。"""
    vault = db.create_vault(name="旅行基金", goal=1000)
    db.add_deposit(vault_id=vault["id"], amount=100)
    assert db.delete_vault(vault["id"]) is True

    assert db.list_vaults() == []
    assert db.list_deposits(vault["id"]) == []
    assert db.delete_vault(vault["id"]) is False


def test_list_deposits_returns_newest_first(db):
    vault = db.create_vault(name="旅行基金", goal=1000)
    db.add_deposit(vault_id=vault["id"], amount=10, note="第一笔")
    db.add_deposit(vault_id=vault["id"], amount=20, note="第二笔")

    deposits = db.list_deposits(vault["id"])
    assert [d["amount"] for d in deposits] == [20.0, 10.0]


# ----------------------------------------------------------------------
# 接口层：新建与列表
# ----------------------------------------------------------------------
def test_create_vault_endpoint(client):
    res = client.post("/api/vaults", json={"name": "旅行基金", "goal": 1000, "icon": "✈️"})
    assert res.status_code == 201

    vault = res.get_json()["vault"]
    assert vault["name"] == "旅行基金"
    assert vault["icon"] == "✈️"
    assert vault["goal"] == 1000.0
    assert vault["saved"] == 0.0


def test_list_vaults_aggregates_total(client):
    client.post("/api/vaults", json={"name": "旅行基金", "goal": 1000})
    client.post("/api/vaults", json={"name": "换电脑", "goal": 0})

    data = client.get("/api/vaults").get_json()
    assert data["count"] == 2
    assert data["total_saved"] == 0.0
    # 新建的排在前面
    assert data["vaults"][0]["name"] == "换电脑"


def test_create_vault_requires_name(client):
    assert client.post("/api/vaults", json={"goal": 100}).status_code == 400
    assert client.post("/api/vaults", json={"name": "   "}).status_code == 400


def test_create_vault_rejects_overlong_name(client):
    assert client.post("/api/vaults", json={"name": "字" * 21}).status_code == 400


def test_create_vault_rejects_negative_goal(client):
    assert client.post("/api/vaults", json={"name": "旅行基金", "goal": -1}).status_code == 400


def test_create_vault_rejects_non_numeric_goal(client):
    assert client.post("/api/vaults", json={"name": "旅行基金", "goal": "很多"}).status_code == 400


def test_create_vault_assigns_palette_color(client):
    """没指定颜色时按已有数量轮取调色板，保证相邻金库颜色不撞。"""
    first = client.post("/api/vaults", json={"name": "A"}).get_json()["vault"]
    second = client.post("/api/vaults", json={"name": "B"}).get_json()["vault"]

    assert first["color"] != second["color"]


def test_create_vault_keeps_valid_custom_color(client):
    vault = client.post("/api/vaults", json={"name": "A", "color": "#123abc"}).get_json()["vault"]
    assert vault["color"] == "#123abc"


# ----------------------------------------------------------------------
# 接口层：存钱
# ----------------------------------------------------------------------
def test_deposit_endpoint_updates_vault(client):
    vault = client.post("/api/vaults", json={"name": "旅行基金", "goal": 1000}).get_json()["vault"]

    res = client.post(f"/api/vaults/{vault['id']}/deposit", json={"amount": 250})
    assert res.status_code == 201

    body = res.get_json()
    assert body["deposited"] == 250.0
    assert body["vault"]["saved"] == 250.0
    assert body["vault"]["progress"] == 0.25


def test_deposit_rejects_invalid_amount(client):
    vault = client.post("/api/vaults", json={"name": "旅行基金"}).get_json()["vault"]
    url = f"/api/vaults/{vault['id']}/deposit"

    assert client.post(url, json={"amount": 0}).status_code == 400
    assert client.post(url, json={"amount": -5}).status_code == 400
    assert client.post(url, json={"amount": "abc"}).status_code == 400
    assert client.post(url, json={}).status_code == 400


def test_deposit_to_missing_vault_returns_404(client):
    assert client.post("/api/vaults/9999/deposit", json={"amount": 10}).status_code == 404


def test_deposit_counts_toward_achieved(client):
    vault = client.post("/api/vaults", json={"name": "换电脑", "goal": 100}).get_json()["vault"]
    body = client.post(f"/api/vaults/{vault['id']}/deposit", json={"amount": 100}).get_json()

    assert body["vault"]["achieved"] is True


# ----------------------------------------------------------------------
# 接口层：流水与删除
# ----------------------------------------------------------------------
def test_deposit_history_endpoint(client):
    vault = client.post("/api/vaults", json={"name": "旅行基金"}).get_json()["vault"]
    client.post(f"/api/vaults/{vault['id']}/deposit", json={"amount": 10, "note": "买咖啡的零钱"})
    client.post(f"/api/vaults/{vault['id']}/deposit", json={"amount": 20})

    data = client.get(f"/api/vaults/{vault['id']}/deposits").get_json()
    assert data["count"] == 2
    assert data["deposits"][0]["amount"] == 20.0
    assert data["deposits"][1]["note"] == "买咖啡的零钱"


def test_deposit_history_of_missing_vault_returns_404(client):
    assert client.get("/api/vaults/9999/deposits").status_code == 404


def test_delete_vault_endpoint(client):
    vault = client.post("/api/vaults", json={"name": "旅行基金"}).get_json()["vault"]
    assert client.delete(f"/api/vaults/{vault['id']}").status_code == 200
    assert client.delete(f"/api/vaults/{vault['id']}").status_code == 404
    assert client.get("/api/vaults").get_json()["count"] == 0


def test_vaults_do_not_pollute_ledger(client):
    """金库是独立的攒钱账本，不能被算进月度收支，否则结余会重复计一次。"""
    vault = client.post("/api/vaults", json={"name": "旅行基金"}).get_json()["vault"]
    client.post(f"/api/vaults/{vault['id']}/deposit", json={"amount": 300})

    summary = client.get("/api/summary").get_json()
    assert summary["income"] == 0.0
    assert summary["expense"] == 0.0
    assert client.get("/api/records").get_json()["count"] == 0
