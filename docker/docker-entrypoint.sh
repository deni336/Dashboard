#!/bin/sh
set -eu

umask 077

CONFIG_FILE="${KASUGAI_CONFIG_FILE:-/data/config.ini}"
CONFIG_DIR="$(dirname "$CONFIG_FILE")"

mkdir -p "$CONFIG_DIR/kasugai/logs" /app/kasugai/resources/backgrounds

if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
[Application]
buttons =
resourcefolder = /app/kasugai/resources/backgrounds/

[AI]
provider = ${KASUGAI_AI_PROVIDER:-disabled}
baseurl = ${KASUGAI_AI_BASE_URL:-}
model = ${KASUGAI_AI_MODEL:-gpt-oss:20b}

[Licensing]
apiurl = ${DENILICENSE_API_URL:-http://denilicense-api:8080}
issuer = ${DENILICENSE_ISSUER:-http://127.0.0.1:8080}
productcode = ${DENILICENSE_PRODUCT_CODE:-KASUGAI}
activationlabel = ${DENILICENSE_ACTIVATION_LABEL:-Kasugai Dashboard}
deviceprivatekey =
activationid =
activationlease =

[WebServer]
port = 8000
address = 0.0.0.0
kasaddress = ${KASUGAI_SERVER_HOST:-kasugai-server}
kasport = ${KASUGAI_SERVER_PORT:-8008}
mediaport = ${KASUGAI_MEDIA_PORT:-50052}
publicurl = ${KASUGAI_PUBLIC_URL:-}
sessionsecret =

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

LEGACY_CONFIG_FILE="${KASUGAI_LEGACY_CONFIG_FILE:-}"
if [ -n "$LEGACY_CONFIG_FILE" ]; then
    python /app/src/license_identity_migration.py \
        --source "$LEGACY_CONFIG_FILE" \
        --destination "$CONFIG_FILE"
fi

python - "$CONFIG_FILE" <<'PY'
import configparser
import os
import sys

from src.config_handler import migrate_background_resources

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
set_value("WebServer", "publicurl", os.getenv("KASUGAI_PUBLIC_URL", ""))
background_folder = "/app/kasugai/resources/backgrounds/"
migrate_background_resources(
    config_file,
    config.get("Application", "resourcefolder", fallback="/app/kasugai/resources/"),
    background_folder,
)
set_value("Application", "resourcefolder", background_folder)
set_value("FileTransfer", "uploadfolder", "/app/kasugai/resources/")
set_value("FileTransfer", "address", os.getenv("KASUGAI_FILE_TRANSFER_HOST", "kasugai-server"))
set_value("FileTransfer", "port", os.getenv("KASUGAI_FILE_TRANSFER_PORT", "50051"))

set_value("Licensing", "apiurl", os.getenv("DENILICENSE_API_URL", "http://denilicense-api:8080"))
set_value("Licensing", "issuer", os.getenv("DENILICENSE_ISSUER", "http://127.0.0.1:8080"))
set_value("Licensing", "productcode", os.getenv("DENILICENSE_PRODUCT_CODE", "KASUGAI").upper())
set_value("Licensing", "activationlabel", os.getenv("DENILICENSE_ACTIVATION_LABEL", "Kasugai Dashboard"))
set_value("AI", "provider", os.getenv("KASUGAI_AI_PROVIDER", "disabled"))
set_value("AI", "baseurl", os.getenv("KASUGAI_AI_BASE_URL", ""))
set_value("AI", "model", os.getenv("KASUGAI_AI_MODEL", "gpt-oss:20b"))

with open(config_file, "w") as file:
    config.write(file)

if not config.get("Licensing", "apiurl", fallback=""):
    print("WARNING: DENILICENSE_API_URL is not set; license login will fail.", file=sys.stderr)
PY

chmod 700 "$CONFIG_DIR" "$CONFIG_DIR/kasugai" "$CONFIG_DIR/kasugai/logs" /app/kasugai/resources /app/kasugai/resources/backgrounds
chmod 600 "$CONFIG_FILE"
find "$CONFIG_DIR" -maxdepth 1 -type f \( -name '*.db' -o -name '*.db-*' \) -exec chmod 600 {} +
find "$CONFIG_DIR/kasugai/logs" -type f -exec chmod 600 {} +
if [ "$(id -u)" = "0" ]; then
    chown -R kasugai:kasugai "$CONFIG_DIR" /app/kasugai/resources
    exec gosu kasugai "$@"
fi
exec "$@"
