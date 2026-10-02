FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADIO_ANALYTICS_ENABLED=False

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./
COPY mockup_tool ./mockup_tool

# UID 1000 trùng user `ubuntu` trên máy chủ: thư mục ./data mount vào ghi được ở cả hai phía.
RUN useradd --uid 1000 --create-home app && mkdir -p /app/data && chown app:app /app/data
USER app

# Trong container phải nghe 0.0.0.0; cổng chỉ mở ra 127.0.0.1 của máy chủ (docker-compose.yml).
ENV HOST=0.0.0.0 PORT=7860 UPLOAD_DIR=/app/data
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/', timeout=4)"]

CMD ["python", "app.py"]
