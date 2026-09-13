"""接口层测试：7 个 REST 接口的主流程与参数校验。"""

from __future__ import annotations


# ----------------------------------------------------------------------
# 健康检查与首页
# ----------------------------------------------------------------------
def test_health_reports_rule_mode_without_credentials(client):
    data = client.get("/api/health").get_json()
    assert data["status"] == "ok"
    assert data["llm"] is False  # 测试环境未配置大模型
    assert data["today"]


def test_index_page_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "小账本" in res.get_data(as_text=True)


# ----------------------------------------------------------------------
# 账单 CRUD
# ----------------------------------------------------------------------
def test_create_and_list_record(client):
    res = client.post(
        "/api/records",
        json={
            "type": "expense",
            "amount": 32,
            "category": "交通",
            "note": "打车",
            "happened_on": "2026-09-12",
        },
    )
    assert res.status_code == 201
    assert res.get_json()["record"]["amount"] == 32.0

    data = client.get("/api/records?month=2026-09").get_json()
    assert data["count"] == 1
    assert data["records"][0]["category"] == "交通"


def test_create_applies_defaults(client):
    record = client.post("/api/records", json={"amount": 10}).get_json()["record"]
    assert record["type"] == "expense"
    assert record["category"] == "其他"
    assert record["happened_on"]


def test_create_rejects_zero_amount(client):
    res = client.post("/api/records", json={"amount": 0})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_create_rejects_non_numeric_amount(client):
    assert client.post("/api/records", json={"amount": "abc"}).status_code == 400


def test_create_rejects_unknown_type(client):
    assert client.post("/api/records", json={"amount": 10, "type": "transfer"}).status_code == 400


def test_create_rejects_malformed_date(client):
    res = client.post("/api/records", json={"amount": 10, "happened_on": "09/12/2026"})
    assert res.status_code == 400


def test_list_records_filters_by_type(client):
    client.post("/api/records", json={"amount": 10, "type": "expense"})
    client.post("/api/records", json={"amount": 500, "type": "income"})
    assert client.get("/api/records?type=income").get_json()["count"] == 1


def test_delete_record_then_404(client):
    record = client.post("/api/records", json={"amount": 10}).get_json()["record"]
    assert client.delete(f"/api/records/{record['id']}").status_code == 200
    assert client.delete(f"/api/records/{record['id']}").status_code == 404


# ----------------------------------------------------------------------
# 一句话解析
# ----------------------------------------------------------------------
def test_parse_endpoint_returns_preview(client):
    res = client.post("/api/parse", json={"text": "昨天打车 32 块"})
    assert res.status_code == 200

    parsed = res.get_json()["parsed"]
    assert parsed["type"] == "expense"
    assert parsed["amount"] == 32.0
    assert parsed["category"] == "交通"
    assert parsed["source"] == "rule"
    assert parsed["raw_text"] == "昨天打车 32 块"


def test_parse_does_not_persist(client):
    """解析接口只做预览，不能写库——否则 AI 出错时会污染账本。"""
    client.post("/api/parse", json={"text": "午饭 25 元"})
    assert client.get("/api/records").get_json()["count"] == 0


def test_parse_requires_text(client):
    assert client.post("/api/parse", json={}).status_code == 400
    assert client.post("/api/parse", json={"text": "  "}).status_code == 400


def test_parse_without_amount_returns_400(client):
    res = client.post("/api/parse", json={"text": "今天很开心"})
    assert res.status_code == 400
    assert "金额" in res.get_json()["error"]


# ----------------------------------------------------------------------
# 统计与洞察
# ----------------------------------------------------------------------
def test_summary_endpoint(client):
    client.post(
        "/api/records", json={"amount": 100, "category": "餐饮", "happened_on": "2026-09-02"}
    )
    client.post(
        "/api/records",
        json={"amount": 500, "type": "income", "category": "工资", "happened_on": "2026-09-01"},
    )

    data = client.get("/api/summary?month=2026-09").get_json()
    assert data["income"] == 500.0
    assert data["expense"] == 100.0
    assert data["balance"] == 400.0
    assert len(data["recent_days"]) == 7


def test_insight_falls_back_to_template(client):
    client.post(
        "/api/records", json={"amount": 300, "category": "餐饮", "happened_on": "2026-09-02"}
    )
    data = client.post("/api/insight", json={"month": "2026-09"}).get_json()

    assert data["source"] == "rule"
    assert "餐饮" in data["text"]


def test_insight_on_empty_month_gives_guidance(client):
    """空账本不该硬凑分析，而应给出引导语。"""
    data = client.post("/api/insight", json={"month": "2026-09"}).get_json()
    assert "还没有" in data["text"]
    assert data["source"] == "rule"
