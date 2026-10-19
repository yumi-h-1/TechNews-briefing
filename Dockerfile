FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY pyproject.toml requirements.lock ./
COPY briefing ./briefing
COPY sources.json ./
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && mkdir -p /data
CMD ["python", "-m", "briefing", "serve"]
