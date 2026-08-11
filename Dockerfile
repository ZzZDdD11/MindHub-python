FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/

EXPOSE 9900

CMD ["sh", "-c", "python -m app.infrastructure.database && exec uvicorn app.main:app --host 0.0.0.0 --port \"${SERVER_PORT:-9900}\""]
