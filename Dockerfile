# syntax=docker/dockerfile:1

FROM python:3.14-slim AS dashboard

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY __init__.py main.py ./
COPY src ./src
COPY sites ./sites
COPY kasugai_server/python ./kasugai_server/python
COPY docker ./docker

RUN mkdir -p /root/Kasugai /app/kasugai/logs /app/kasugai/resources

EXPOSE 8000

ENTRYPOINT ["sh", "/app/docker/docker-entrypoint.sh"]
CMD ["waitress-serve", "--host=0.0.0.0", "--port=8000", "src.wsgi:app"]

FROM golang:1.24-alpine AS server-builder

WORKDIR /src/kasugai_server

COPY kasugai_server/go.mod kasugai_server/go.sum ./
RUN go mod download

COPY kasugai_server/ ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kasugai-server .

FROM alpine:3.20 AS kasugai-server

WORKDIR /app

COPY --from=server-builder /out/kasugai-server /app/kasugai-server
COPY docker/server-config.json /app/config.json

EXPOSE 8008 50051 50052

CMD ["/app/kasugai-server"]

FROM dashboard AS final
