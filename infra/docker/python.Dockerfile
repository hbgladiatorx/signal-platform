# infra/docker/python.Dockerfile
# Shared Dockerfile for all Python services in the platform.
# The actual command is set per-service in docker-compose.yml.

FROM python:3.12-slim AS base

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir --quiet uv==0.4.30

# System dependencies: postgres client for diagnostics, curl for health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifests first for better Docker layer caching
COPY pyproject.toml ./

# Install Python dependencies from pyproject.toml
RUN uv pip install --system --no-cache .

# Copy application code
COPY packages ./packages
COPY services ./services
COPY strategies ./strategies
COPY migrations ./migrations
# referee/ is the certification engine; the /referee API router imports it, so it
# must be in the image (it was previously CLI-only and uncopied).
COPY referee ./referee

# Ensure imports work from any subdirectory
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command — overridden per service in docker-compose.yml
CMD ["python", "-c", "print('No command specified. Override in docker-compose.yml')"]
