FROM python:3.12-slim

WORKDIR /app

# LLM 调用经 zode_client.js（node 子进程，仅用内置 https 模块）发出，
# 故镜像需装 Node.js；否则运行时报 [Errno 2] No such file or directory: 'node'。
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# 结构化教材 YAML（教材同步学习页数据源）。backend 被平铺到 /app，
# loader 会在 /app/textbooks/structured 查找，故放到该路径下。
COPY textbooks/structured/ ./textbooks/structured/

# 历史时空地图与游戏 LLM 出题所需的小数据（geo_events.json + corpus.json）。
# .dockerignore 已放行 knowledge_base/history；loader 会在 /app/knowledge_base/history 查找。
COPY knowledge_base/ ./knowledge_base/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
