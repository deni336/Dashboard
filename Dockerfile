# syntax=docker/dockerfile:1

FROM python:3.14-slim@sha256:d3400aa122fa42cf0af0dbe8ec3091b047eac5c8f7e3539f7135e86d855dc015 AS dashboard

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && groupadd --system kasugai \
    && useradd --system --gid kasugai --home-dir /data --shell /usr/sbin/nologin kasugai

COPY __init__.py main.py ./
COPY src ./src
COPY sites ./sites
COPY kasugai_server/python ./kasugai_server/python
COPY docker ./docker

RUN mkdir -p /data/kasugai/logs /app/kasugai/resources \
    && chown -R kasugai:kasugai /data /app/kasugai

ENV KASUGAI_CONFIG_FILE=/data/config.ini

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=3).close()"]

ENTRYPOINT ["sh", "/app/docker/docker-entrypoint.sh"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "src.wsgi:app"]

FROM golang:1.26-alpine3.24@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS server-builder

WORKDIR /src/kasugai_server

COPY kasugai_server/go.mod kasugai_server/go.sum ./
RUN go mod download

COPY kasugai_server/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kasugai-server .

FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS kasugai-server

WORKDIR /app

RUN addgroup -S kasugai && adduser -S -G kasugai kasugai \
    && mkdir -p /data && chown -R kasugai:kasugai /app /data
COPY --from=server-builder /out/kasugai-server /app/kasugai-server
COPY docker/server-config.json /app/config.json

USER kasugai
EXPOSE 8008 50051 50052
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["sh", "-c", "nc -z -w 2 127.0.0.1 8008 && nc -z -w 2 127.0.0.1 50051 && nc -z -w 2 127.0.0.1 50052"]

CMD ["/app/kasugai-server"]

FROM dashboard AS final
