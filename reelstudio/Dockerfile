ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-inter fonts-liberation2 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY fonts ./fonts
RUN pip install --no-cache-dir ".[postgres]"
ENV RS_DATA_DIR=/data
VOLUME /data
CMD ["reelstudio", "serve", "--host", "0.0.0.0", "--port", "8000"]
