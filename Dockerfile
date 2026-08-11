FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9900

CMD ["sh", "-c", "python -m app.infrastructure.database && exec uvicorn app.main:app --host 0.0.0.0 --port 9900"]
