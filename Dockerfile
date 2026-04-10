FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

# Install system dev dependencies required for postgres and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and metadata
COPY pyproject.toml .

# Copy application layers
COPY centrag/ ./centrag/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Leverage Python pip install per standard rule guidelines
RUN pip install .

# Expose API App Port
EXPOSE 8000

# Start Uvicorn FastAPI process
CMD ["uvicorn", "centrag.app:app", "--host", "0.0.0.0", "--port", "8000"]
