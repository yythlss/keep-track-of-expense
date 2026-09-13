"""记账小助手 · 启动入口。

- 本地运行：`python run.py`
- 容器运行：Dockerfile 的 CMD 会执行它，监听 0.0.0.0:8686（CNB 预览端口）

注意：必须监听 0.0.0.0，否则 CNB 端口预览 / 容器外部无法访问。
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8686"))
    print(f"🐷 小账本已启动： http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
