FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# Shell form (not exec form) so $PORT is expanded by sh before uvicorn sees
# it. Exec form would pass the literal string "${PORT:-8000}" to uvicorn,
# which fails to parse it as an int. Railway injects PORT at runtime.
CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
