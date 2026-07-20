# ───────────────────────────────────────────
# Dockerfile — Telegram Bot Tuya Smart Home
# ───────────────────────────────────────────

FROM python:3.11-slim

# Prevent Python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Run as root inside container so bind-mounted volumes are writable
# (Host file ownership is the actual security boundary in single-node Docker)
CMD ["python", "run.py"]
