FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install backend-only deps first for better layer caching.
COPY requirements-backend.txt ./
RUN pip install --no-cache-dir -r requirements-backend.txt

# Copy the rest of the repo (backend/, shared/, dashboard/, etc.).
COPY . .

EXPOSE 8000

# Railway injects $PORT; default to 8000 locally. Use sh -c so $PORT expands.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
