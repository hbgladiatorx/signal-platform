# infra/docker/test.Dockerfile
# Test image: the runtime app plus the dev test toolchain and the tests/ tree.
# Kept separate from python.Dockerfile so production images never ship pytest.
#
# Run:  docker compose --profile test run --rm test
#       docker compose --profile test run --rm test pytest tests/test_position_math.py -q

FROM python:3.12-slim AS test

RUN pip install --no-cache-dir --quiet uv==0.4.30

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./

# Project runtime deps + the dev test toolchain.
RUN uv pip install --system --no-cache . \
        pytest>=8.3.0 pytest-asyncio>=0.24.0 pytest-cov>=5.0.0

COPY packages ./packages
COPY services ./services
COPY strategies ./strategies
COPY migrations ./migrations
COPY tests ./tests

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["pytest", "-q"]
