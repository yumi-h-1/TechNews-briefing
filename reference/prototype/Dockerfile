FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY briefing ./briefing
COPY sources.json ./
RUN mkdir -p /data
CMD ["python", "-m", "briefing", "serve"]
