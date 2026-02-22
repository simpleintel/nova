FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080

# Run with gunicorn + gevent for WebSocket support
CMD exec gunicorn --bind 0.0.0.0:$PORT --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker --workers 1 --threads 1 --timeout 120 app:app
