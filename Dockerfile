FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY alembic.ini ./
COPY alembic ./alembic

RUN chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); raise SystemExit(response.status != 200)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
