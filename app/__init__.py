"""Flask 应用工厂：装配数据层、API 蓝图与静态页面。"""

from __future__ import annotations

import os

from flask import Flask, send_from_directory

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")


def create_app() -> Flask:
    """创建并返回 Flask 应用实例。"""
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    # 让 jsonify 直接输出中文，而不是 \\uXXXX 转义
    app.json.ensure_ascii = False

    from .db import init_db

    init_db()

    from .routes import api

    app.register_blueprint(api)

    @app.get("/")
    def index():
        """首页：单页应用入口。"""
        return send_from_directory(STATIC_DIR, "index.html")

    @app.after_request
    def _prevent_stale_cache(response):
        """避免浏览器拿旧页面：HTML 不缓存，静态资源每次回源校验。

        否则改完前端、重建镜像之后，浏览器仍可能用缓存里的旧 index.html，
        让人误以为改动没生效。
        """
        if (response.mimetype or "") == "text/html":
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app
