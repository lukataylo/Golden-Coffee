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

# Railway injects $PORT. start.sh runs the backend hub + the in-container actuator
# executor (drives the Xiaomi Wi-Fi light over the Mi cloud) so the deployed
# dashboard controls real devices during the demo.
CMD ["sh", "start.sh"]
