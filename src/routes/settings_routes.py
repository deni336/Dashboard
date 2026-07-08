# routes/settings_routes.py
from flask import Blueprint, request, jsonify
from src.global_logger import GlobalLogger

settings_bp = Blueprint('settings_bp', __name__)
logger = GlobalLogger.get_logger("SettingsRoutes")

VALID_LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')

config = None  # Will be set from WebServer

def init_settings_routes(cfg):
    global config
    config = cfg

@settings_bp.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify({
        'loglevel': config.get('Logging', 'loglevel'),
        'uploadfolder': config.get('FileTransfer', 'uploadfolder'),
    }), 200

@settings_bp.route('/api/settings', methods=['POST'])
def update_settings():
    data = request.get_json(silent=True) or {}

    loglevel = data.get('loglevel')
    if loglevel is not None:
        loglevel = loglevel.strip().upper()
        if loglevel not in VALID_LOG_LEVELS:
            return jsonify({"error": f"loglevel must be one of {', '.join(VALID_LOG_LEVELS)}"}), 400
        config.set('Logging', 'loglevel', loglevel)

    uploadfolder = data.get('uploadfolder')
    if uploadfolder is not None:
        uploadfolder = uploadfolder.strip()
        if not uploadfolder:
            return jsonify({"error": "uploadfolder cannot be empty"}), 400
        config.set('FileTransfer', 'uploadfolder', uploadfolder)

    return jsonify({
        'loglevel': config.get('Logging', 'loglevel'),
        'uploadfolder': config.get('FileTransfer', 'uploadfolder'),
    }), 200
