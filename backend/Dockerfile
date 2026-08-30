FROM python:3.12-slim

WORKDIR /app

# Production images only need runtime dependencies. requirements.txt is the
# development/CI compatibility entry point and also includes ../eval, which is
# intentionally excluded from the Docker build context.
COPY backend/requirements-runtime.txt .
COPY constraints-runtime.txt .
RUN pip install --no-cache-dir --constraint constraints-runtime.txt --requirement requirements-runtime.txt

COPY backend/ .

# 结构化教材 YAML（教材同步学习页数据源）。backend 被平铺到 /app，
# loader 会在 /app/textbooks/structured 查找，故放到该路径下。
COPY textbooks/structured/ ./textbooks/structured/

# 历史时空地图与游戏 LLM 出题所需的小数据（geo_events.json + corpus.json）。
# .dockerignore 已放行 knowledge_base/history；loader 会在 /app/knowledge_base/history 查找。
COPY knowledge_base/ ./knowledge_base/

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.data \
    && chown -R appuser:appuser /app/.data

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Render Web Services use port 10000 by default. start_backend.py still honors
# an injected PORT, while local Compose explicitly overrides this to 8000.
ENV PORT=10000

USER appuser

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '10000') + '/api/health', timeout=3)"]

CMD ["python", "start_backend.py"]
