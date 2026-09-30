FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание непривилегированного пользователя app (UID 1000)
RUN useradd -m -u 1000 -s /bin/bash app && \
    mkdir -p /data /app && \
    chown -R app:app /data /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY --chown=app:app . .

RUN chown -R app:app /app /data

USER app

VOLUME ["/data"]

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; port=os.getenv('PORT') or os.getenv('CARNAVAL_PORT', '8765'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')"

CMD ["python", "-u", "main.py"]
