FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY briefing ./briefing
COPY sources.json ./
RUN uv sync --locked --no-dev --no-editable && mkdir -p /data
CMD ["python", "-m", "briefing", "serve"]
