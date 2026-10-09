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
# Editable install on purpose: config/, migrations/ and alembic.ini are located relative to the source tree (/app).
RUN pip install --no-cache-dir -e ".[postgres]"
RUN useradd --uid 1000 --create-home app && mkdir /data && chown app:app /data
USER app
ENV RS_DATA_DIR=/data RS_CONFIG_DIR=/app/config RS_DATABASE_URL=sqlite:////data/reelstudio.db
VOLUME /data
CMD ["reelstudio", "serve", "--host", "0.0.0.0", "--port", "8000"]
