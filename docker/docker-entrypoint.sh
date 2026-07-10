#!/bin/sh
set -eu

CONFIG_FILE="${KASUGAI_CONFIG_FILE:-/root/Kasugai/config.ini}"
CONFIG_DIR="$(dirname "$CONFIG_FILE")"

mkdir -p "$CONFIG_DIR" /root/Kasugai/kasugai/logs /app/kasugai/resources

if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
[Application]
buttons =
clientid = ${GOOGLE_CLIENT_ID:-}
clientsecret = ${GOOGLE_CLIENT_SECRET:-}

[WebServer]
port = 8000
address = 0.0.0.0
kasaddress = ${KASUGAI_SERVER_HOST:-kasugai-server}
kasport = ${KASUGAI_SERVER_PORT:-8008}
mediaport = ${KASUGAI_MEDIA_PORT:-50052}

[Logging]
path = kasugai/logs/
loglevel = INFO

[FileTransfer]
uploadfolder = /app/kasugai/resources/
address = ${KASUGAI_FILE_TRANSFER_HOST:-kasugai-server}
port = ${KASUGAI_FILE_TRANSFER_PORT:-50051}

[Database]
dbpath = chat_history.db
encryption_key =
EOF
fi

exec "$@"
