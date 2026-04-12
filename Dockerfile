FROM python:3.12-slim

# Set environment variables for resilience
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PORT=8000

WORKDIR /app

# Install system dev dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 1. Copy application files (necessary for pip install of the local package)
COPY pyproject.toml .
COPY centrag/ ./centrag/
COPY alembic/ ./alembic/
COPY alembic.ini .

# 2. Install dependencies with extended timeout
RUN pip install --upgrade pip && \
    pip install .

# Expose API App Port
EXPOSE 8000

# Start Uvicorn FastAPI process
CMD ["uvicorn", "centrag.app:app", "--host", "0.0.0.0", "--port", "8000"]
