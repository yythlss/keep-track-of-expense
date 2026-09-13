"""CNB 大模型接口封装（OpenAI 兼容，平台限定流式调用）。

环境变量优先级（与课程第 3 章一致）：
1. `BASE_URL` + `API_KEY`（本地开发手动填写）
2. `CNB_API_ENDPOINT` + `CNB_REPO_SLUG` + `CNB_TOKEN`（云端平台自动注入）

未配置时 `available()` 返回 False，上层业务会自动降级到规则通道，
因此“没有大模型也能点一下就跑起来”。
"""

from __future__ import annotations

import os
from typing import Optional

try:  # 本地读取 .env，容器里没有该文件也不影响
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv 不是硬依赖
    pass


def _base_url() -> Optional[str]:
    base_url = os.environ.get("BASE_URL")
    if base_url:
        return base_url.rstrip("/")
    endpoint = os.environ.get("CNB_API_ENDPOINT")
    slug = os.environ.get("CNB_REPO_SLUG")
    if endpoint and slug:
        return f"{endpoint.rstrip('/')}/{slug}/-/ai-ide/v2"
    return None


def _api_key() -> Optional[str]:
    return os.environ.get("API_KEY") or os.environ.get("CNB_TOKEN")


def model_id() -> str:
    return os.environ.get("MODEL_ID", "deepseek-v4-flash")


def available() -> bool:
    """大模型是否可用（判断依据：地址与密钥是否齐全）。"""
    return bool(_base_url() and _api_key())


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """调用大模型并返回完整文本。

    CNB 云端接口只支持 `stream=True`，这里统一走流式再拼接，
    这样本地与云端可以用同一份代码。
    """
    if not available():
        raise RuntimeError("大模型未配置：缺少 BASE_URL / API_KEY（或 CNB 注入的环境变量）")

    from openai import OpenAI  # 延迟导入，未使用 AI 功能时无需安装即可跑规则版

    client = OpenAI(
        base_url=_base_url(),
        api_key=_api_key(),
        timeout=float(os.environ.get("LLM_TIMEOUT", "60")),
    )
    stream = client.chat.completions.create(
        model=model_id(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    parts: list[str] = []
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            parts.append(delta.content)
    return "".join(parts).strip()
