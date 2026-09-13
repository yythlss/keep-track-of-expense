# ==========================================================================
# 小账本 · 镜像定义（python:3.12-slim）
#
# 构建：docker build -t money:local .
# 运行：docker run -d -p 8686:8686 -v money-data:/app/data money:local
#
# 两个关键点：
#   1. 先 COPY requirements.txt 再装依赖，最后 COPY 源码——改代码不会触发
#      依赖重装，充分利用 Docker 分层缓存；
#   2. 必须监听 0.0.0.0，否则 CNB 端口预览无法访问。
# ==========================================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8686

WORKDIR /app

# ---- 第 1 层：依赖（很少变动）--------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- 第 2 层：源码（经常变动）--------------------------------------------
COPY app ./app
COPY static ./static
COPY run.py ./

# ---- 数据目录：可挂 volume 持久化账本 -----------------------------------
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# ---- 非 root 运行 --------------------------------------------------------
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8686

CMD ["python", "run.py"]
