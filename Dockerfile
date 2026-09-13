FROM denoland/deno:bin-2.5.6 AS deno
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .
RUN useradd --create-home uvdb && mkdir -p /app/storage/temp && chown -R uvdb:uvdb /app
USER uvdb
CMD ["arq", "app.worker.WorkerSettings"]

