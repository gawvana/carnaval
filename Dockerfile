FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Системные зависимости при необходимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .

# Постоянные директории (монтируются через volume на хостинге)
VOLUME ["/app/configs", "/app/logs", "/app/storage", "/app/plugins"]

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, os; port=os.getenv('PORT') or os.getenv('CARNAVAL_PORT', '8765'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/meta')"

CMD ["python", "-u", "main.py"]
