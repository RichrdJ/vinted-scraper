FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8344

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persisted database + logs live here.
VOLUME ["/app/data"]

EXPOSE 8344

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('WEB_PORT','8344'), timeout=4)" || exit 1

CMD ["python", "main.py"]
