FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persisted database + logs live here.
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["python", "main.py"]
