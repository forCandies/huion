# syntax=docker/dockerfile:1.7
ARG LIVESYNC_COMMIT=ba297d12338d783161cdf788703ae1d2c3658ee0

FROM node:22-slim AS livesync-source
ARG LIVESYNC_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /source
RUN curl -fsSL "https://github.com/vrtmrz/obsidian-livesync/archive/${LIVESYNC_COMMIT}.tar.gz" -o source.tar.gz \
    && tar -xzf source.tar.gz --strip-components=1 \
    && npm install \
    && npm run build -w self-hosted-livesync-cli

FROM node:22-slim AS livesync-deps
COPY --from=livesync-source /source/src/apps/cli/package.json /deps/package.json
WORKDIR /deps
RUN apt-get update && apt-get install -y --no-install-recommends python3 make g++ \
    && npm pkg delete devDependencies \
    && npm install --omit=dev \
    && rm -rf /var/lib/apt/lists/*

FROM node:22-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=livesync-source /source/src/apps/cli/dist /opt/livesync/dist
COPY --from=livesync-deps /deps/node_modules /opt/livesync/node_modules
COPY --chmod=755 deploy/livesync-cli.sh /usr/local/bin/livesync-cli
COPY app/ ./app/
COPY tests/ ./tests/
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
