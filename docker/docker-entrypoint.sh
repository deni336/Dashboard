#!/bin/sh
set -eu

CONFIG_FILE="${KASUGAI_CONFIG_FILE:-/root/Kasugai/config.ini}"
CONFIG_DIR="$(dirname "$CONFIG_FILE")"

mkdir -p "$CONFIG_DIR" /root/Kasugai/kasugai/logs /app/kasugai/resources

if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
[Application]
buttons =

[Licensing]
apiurl = ${DENILICENSE_API_URL:-http://denilicense-api:8080}
issuer = ${DENILICENSE_ISSUER:-http://127.0.0.1:8080}
productcode = ${DENILICENSE_PRODUCT_CODE:-KASUGAI}
activationlabel = ${DENILICENSE_ACTIVATION_LABEL:-Kasugai Dashboard}
deviceprivatekey =

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
projectdbpath = project_manager.db
encryption_key =
EOF
fi

python - "$CONFIG_FILE" <<'PY'
import configparser
import os
import sys

config_file = sys.argv[1]
config = configparser.ConfigParser()
config.read(config_file)

def set_value(section, option, value, overwrite_blank_only=False):
    if not config.has_section(section):
        config.add_section(section)
    current = config.get(section, option, fallback="")
    if value and (not overwrite_blank_only or not current):
        config.set(section, option, value)

set_value("WebServer", "address", "0.0.0.0")
set_value("WebServer", "kasaddress", os.getenv("KASUGAI_SERVER_HOST", "kasugai-server"))
set_value("WebServer", "kasport", os.getenv("KASUGAI_SERVER_PORT", "8008"))
set_value("WebServer", "mediaport", os.getenv("KASUGAI_MEDIA_PORT", "50052"))
set_value("FileTransfer", "uploadfolder", "/app/kasugai/resources/")
set_value("FileTransfer", "address", os.getenv("KASUGAI_FILE_TRANSFER_HOST", "kasugai-server"))
set_value("FileTransfer", "port", os.getenv("KASUGAI_FILE_TRANSFER_PORT", "50051"))

set_value("Licensing", "apiurl", os.getenv("DENILICENSE_API_URL", "http://denilicense-api:8080"))
set_value("Licensing", "issuer", os.getenv("DENILICENSE_ISSUER", "http://127.0.0.1:8080"))
set_value("Licensing", "productcode", os.getenv("DENILICENSE_PRODUCT_CODE", "KASUGAI").upper())
set_value("Licensing", "activationlabel", os.getenv("DENILICENSE_ACTIVATION_LABEL", "Kasugai Dashboard"))

with open(config_file, "w") as file:
    config.write(file)

if not config.get("Licensing", "apiurl", fallback=""):
    print("WARNING: DENILICENSE_API_URL is not set; license login will fail.", file=sys.stderr)
PY

exec "$@"
