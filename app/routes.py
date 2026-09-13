"""REST API 蓝图：账单 CRUD、一句话解析、月度统计、AI 洞察与桌宠。"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from flask import Blueprint, jsonify, request

from . import db, insights, llm, parser, pet

api = Blueprint("api", __name__, url_prefix="/api")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# 允许的图片 MIME，配合 _is_image_data_url 判断头像 / 背景是否合法
_IMAGE_MIMES = {"png", "jpeg", "jpg", "webp", "gif", "avif"}


def _is_image_data_url(value: str) -> bool:
    """判断是否为图片 data URL。

    刻意不用正则：base64 可能长达上百 KB，字符串判断更省时也更直观。
    """
    head, _, body = value.partition(",")
    if not body or not head.startswith("data:image/") or not head.endswith(";base64"):
        return False
    mime = head[len("data:image/"): -len(";base64")]
    return mime in _IMAGE_MIMES


# ----------------------------------------------------------------------
# 健康检查
# ----------------------------------------------------------------------
@api.get("/health")
def health():
    """返回服务状态与 AI 可用性，前端据此显示角标。"""
    return jsonify(
        status="ok",
        llm=llm.available(),
        model=llm.model_id(),
        today=date.today().isoformat(),
    )


# ----------------------------------------------------------------------
# 账单 CRUD
# ----------------------------------------------------------------------
@api.get("/records")
def get_records():
    """查询账单列表，支持 month / date / category / type 过滤。"""
    on = (request.args.get("date") or "").strip() or None
    if on and not _DATE_RE.match(on):
        return jsonify(error="date 格式应为 YYYY-MM-DD"), 400

    records = db.list_records(
        month=request.args.get("month") or None,
        on=on,
        category=request.args.get("category") or None,
        type=request.args.get("type") or None,
        limit=min(int(request.args.get("limit", 200)), 500),
    )
    return jsonify(records=records, count=len(records))


@api.post("/records")
def create_record():
    """新增一条账单（手动记账或确认 AI 解析结果时调用）。"""
    payload = request.get_json(silent=True) or {}
    try:
        fields = _validate_record(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(record=db.add_record(**fields)), 201


@api.delete("/records/<int:record_id>")
def remove_record(record_id: int):
    """删除一条账单。"""
    if not db.delete_record(record_id):
        return jsonify(error="记录不存在"), 404
    return jsonify(deleted=record_id)


# ----------------------------------------------------------------------
# 一句话记账
# ----------------------------------------------------------------------
@api.post("/parse")
def parse_sentence():
    """把自然语言解析成结构化账单（只返回预览，不落库）。"""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify(error="请输入记账内容"), 400

    try:
        parsed = parser.parse_text(text)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    parsed["raw_text"] = text
    return jsonify(parsed=parsed)


# ----------------------------------------------------------------------
# 金库
# ----------------------------------------------------------------------
@api.get("/vaults")
def get_vaults():
    """所有金库及其已存金额、存钱次数、攒钱进度。"""
    vaults = db.list_vaults()
    return jsonify(
        vaults=vaults,
        count=len(vaults),
        total_saved=round(sum(v["saved"] for v in vaults), 2),
    )


@api.post("/vaults")
def create_vault():
    """按需新建一个金库。"""
    payload = request.get_json(silent=True) or {}
    try:
        fields = _validate_vault(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(vault=db.create_vault(**fields)), 201


@api.delete("/vaults/<int:vault_id>")
def remove_vault(vault_id: int):
    """删除金库及其全部存钱记录。"""
    if not db.delete_vault(vault_id):
        return jsonify(error="金库不存在"), 404
    return jsonify(deleted=vault_id)


@api.post("/vaults/<int:vault_id>/deposit")
def deposit_into_vault(vault_id: int):
    """存钱入库，返回更新后的金库（前端据此播放金币入罐动画）。"""
    payload = request.get_json(silent=True) or {}
    try:
        amount, note = _validate_deposit(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    vault = db.add_deposit(vault_id=vault_id, amount=amount, note=note)
    if vault is None:
        return jsonify(error="金库不存在"), 404
    return jsonify(vault=vault, deposited=round(amount, 2)), 201


@api.get("/vaults/<int:vault_id>/deposits")
def get_vault_deposits(vault_id: int):
    """某个金库的存钱流水。"""
    if db.get_vault(vault_id) is None:
        return jsonify(error="金库不存在"), 404
    limit = min(int(request.args.get("limit", 20)), 200)
    deposits = db.list_deposits(vault_id, limit=limit)
    return jsonify(deposits=deposits, count=len(deposits))


# ----------------------------------------------------------------------
# 日历视图
# ----------------------------------------------------------------------
@api.get("/calendar")
def get_calendar():
    """按月返回逐日收支，供日历格子渲染。"""
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        return jsonify(error="month 格式应为 YYYY-MM"), 400
    return jsonify(db.calendar(month))


# ----------------------------------------------------------------------
# 个性化（头像 / 昵称 / 背景）
# ----------------------------------------------------------------------
@api.get("/settings")
def get_settings():
    """读取界面偏好，未设置项返回默认值。"""
    return jsonify(settings=db.get_settings())


@api.put("/settings")
def put_settings():
    """部分更新界面偏好，只覆盖本次传入的字段。"""
    payload = request.get_json(silent=True) or {}
    try:
        patch = _validate_settings(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    try:
        return jsonify(settings=db.save_settings(patch))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


# ----------------------------------------------------------------------
# 统计与洞察
# ----------------------------------------------------------------------
@api.get("/summary")
def get_summary():
    """某月收支统计。"""
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    return jsonify(db.summary(month))


@api.post("/insight")
def post_insight():
    """生成某月的 AI 消费洞察。"""
    payload = request.get_json(silent=True) or {}
    month = payload.get("month") or request.args.get("month")
    return jsonify(insights.generate_insight(month))


# ----------------------------------------------------------------------
# AI 桌宠
# ----------------------------------------------------------------------
@api.get("/pet/greeting")
def pet_greeting():
    """桌宠的开场白：跟着当前账本走，一开口就有信息量。"""
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        return jsonify(error="month 格式应为 YYYY-MM"), 400
    return jsonify(pet.greeting(month))


@api.post("/pet/chat")
def pet_chat():
    """和桌宠说一句话，回一句外加一个心情。"""
    payload = request.get_json(silent=True) or {}
    month = payload.get("month")
    if month and not _MONTH_RE.match(str(month)):
        return jsonify(error="month 格式应为 YYYY-MM"), 400

    try:
        reply = pet.chat(payload.get("message", ""), month=month)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(reply)


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def _validate_record(payload: dict) -> dict:
    """校验并规整手动录入的账单项。"""
    type_ = payload.get("type", "expense")
    if type_ not in ("expense", "income"):
        raise ValueError("type 必须是 expense 或 income")

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("金额必须是数字")
    if amount <= 0:
        raise ValueError("金额必须大于 0")

    category = (payload.get("category") or "其他").strip() or "其他"
    note = (payload.get("note") or "").strip()[:50]

    happened_on: Optional[str] = (payload.get("happened_on") or "").strip() or None
    if happened_on and not _DATE_RE.match(happened_on):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    happened_on = happened_on or date.today().isoformat()

    return {
        "type": type_,
        "amount": amount,
        "category": category,
        "note": note,
        "happened_on": happened_on,
    }


def _validate_vault(payload: dict) -> dict:
    """校验新建金库的入参。"""
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("请给金库起个名字")
    if len(name) > 20:
        raise ValueError("金库名称不能超过 20 个字")

    try:
        goal = float(payload.get("goal") or 0)
    except (TypeError, ValueError):
        raise ValueError("目标金额必须是数字")
    if goal < 0:
        raise ValueError("目标金额不能为负数")

    icon = (payload.get("icon") or "").strip()[:4] or db.VAULT_ICONS[0]

    color = (payload.get("color") or "").strip()
    if not _COLOR_RE.match(color):
        # 没指定就按已有金库数量轮取调色板，让相邻金库颜色不撞
        color = db.VAULT_COLORS[len(db.list_vaults()) % len(db.VAULT_COLORS)]

    return {
        "name": name,
        "goal": goal,
        "icon": icon,
        "color": color,
        "note": (payload.get("note") or "").strip()[:50],
    }


def _validate_deposit(payload: dict) -> tuple[float, str]:
    """校验存钱入参，返回 (金额, 备注)。"""
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("存入金额必须是数字")
    if amount <= 0:
        raise ValueError("存入金额必须大于 0")
    if amount > 10_000_000:
        raise ValueError("单次存入金额过大")

    return round(amount, 2), (payload.get("note") or "").strip()[:50]


def _validate_settings(payload: dict) -> dict:
    """校验个性化设置：头像 / 背景只收 emoji 或图片 data URL。"""
    patch: dict = {}

    if "nickname" in payload:
        patch["nickname"] = (payload.get("nickname") or "").strip()[:12]

    if "avatar" in payload:
        avatar = str(payload.get("avatar") or "").strip()
        if not avatar:
            avatar = db.DEFAULT_SETTINGS["avatar"]  # 清空即回到默认头像
        elif avatar.startswith("data:"):
            if not _is_image_data_url(avatar):
                raise ValueError("头像图片格式不支持，请换一张 PNG / JPG")
        elif len(avatar) > 4:
            raise ValueError("头像请使用 emoji 或上传图片")
        patch["avatar"] = avatar

    if "bg_preset" in payload:
        preset = str(payload.get("bg_preset") or "").strip()
        if preset not in db.BG_PRESETS:
            raise ValueError("背景主题不存在")
        patch["bg_preset"] = preset

    if "bg_image" in payload:
        image = str(payload.get("bg_image") or "").strip()
        if image and not _is_image_data_url(image):
            raise ValueError("背景图片格式不支持，请换一张 PNG / JPG")
        patch["bg_image"] = image  # 传空字符串即恢复预设背景

    return patch
