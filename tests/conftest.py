"""pytest 公共夹具。

两个原则：
1. **隔离数据库**——每个用例一个临时库，绝不碰开发数据；
2. **隔离外部依赖**——清空大模型相关环境变量，让测试在无网络、无凭证的
   CI 环境里也能全绿（AI 通道单独用 monkeypatch 打桩验证）。
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 大模型相关的全部环境变量，测试中一律清空
_LLM_ENV_KEYS = (
    "BASE_URL",
    "API_KEY",
    "MODEL_ID",
    "CNB_API_ENDPOINT",
    "CNB_REPO_SLUG",
    "CNB_TOKEN",
)


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """把数据库指向临时文件，并断开大模型。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    for key in _LLM_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


@pytest.fixture()
def db(isolated_env):
    """已建好表的临时数据层。"""
    from app import db as db_module

    db_module.init_db()
    return db_module


@pytest.fixture()
def client(isolated_env):
    """Flask 测试客户端。"""
    from app import create_app

    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client
