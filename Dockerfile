FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY pokeping/ pokeping/
COPY config.yaml .

# Create data directory for SQLite database
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV POKEPING_DB_PATH=/app/data/pokeping.db

VOLUME ["/app/data"]

ENTRYPOINT ["python", "-m", "pokeping"]
