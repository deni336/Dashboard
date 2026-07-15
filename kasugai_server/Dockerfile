# syntax=docker/dockerfile:1
FROM golang:1.26-alpine3.24@sha256:0178a641fbb4858c5f1b48e34bdaabe0350a330a1b1149aabd498d0699ff5fb2 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kasugai-server .

FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b
RUN addgroup -S kasugai && adduser -S -G kasugai kasugai \
    && mkdir -p /app /data && chown -R kasugai:kasugai /app /data
WORKDIR /app
COPY --from=builder /out/kasugai-server /app/kasugai-server
COPY config.vps.json /app/config.json
USER kasugai
EXPOSE 8008 50051 50052
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["sh", "-c", "nc -z -w 2 127.0.0.1 8008 && nc -z -w 2 127.0.0.1 50051 && nc -z -w 2 127.0.0.1 50052"]
ENTRYPOINT ["/app/kasugai-server"]
