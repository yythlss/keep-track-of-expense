# 纯前端静态站点 用 python 内置 http.server 托管 无需任何依赖
FROM python:3.12-slim

WORKDIR /app
COPY . .

ENV PORT=8686
EXPOSE 8686

# --bind 0.0.0.0 才能被 CNB 端口预览访问
CMD ["sh", "-c", "python -m http.server ${PORT} --bind 0.0.0.0"]
