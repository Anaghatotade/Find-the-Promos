# Container image for any Docker host (Render's Docker runtime, Railway, Koyeb, Google Cloud Run, a VPS).
# Render's simplest path is render.yaml (native Python runtime, no Docker needed).
# Runs as a non-root user; listens on $PORT (hosts set it; default 7860).
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PORT=7860 PROMOFINDER_PUBLIC=1 PROMOFINDER_DATA_DIR=/tmp/promofinder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1000 app && mkdir -p /tmp/promofinder && chown -R app /tmp/promofinder
USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/healthz')"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
