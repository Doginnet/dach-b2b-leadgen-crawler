FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY config ./config
COPY src ./src
COPY scrapy.cfg ./
COPY data/samples ./data/samples

RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uv", "run", "leadgen-web"]
