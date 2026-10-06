FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project metadata first for layer caching
COPY pyproject.toml uv.lock alembic.ini README.md ./
COPY realm/ ./realm/

RUN uv sync --frozen --no-dev

# Run as a non-root user
RUN useradd --create-home --shell /usr/sbin/nologin realm
USER realm

ENV PATH=/app/.venv/bin:$PATH

CMD ["realm", "api"]
