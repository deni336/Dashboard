import base64
import binascii
from flask import Blueprint, request, jsonify
from src.global_logger import GlobalLogger
import src.routes.chat_routes as chat_routes

screenshare_bp = Blueprint('screenshare_bp', __name__)
logger = GlobalLogger.get_logger("ScreenshareRoutes")

MAX_SCREEN_FRAME_BYTES = 1_500_000


def _read_frame_bytes():
    if request.is_json:
        data = request.get_json(silent=True) or {}
        b64_data = data.get('data')
        if not b64_data:
            return None, "No frame data provided"
        try:
            frame_bytes = base64.b64decode(b64_data, validate=True)
        except (binascii.Error, ValueError):
            return None, "Invalid base64 frame data"
    else:
        if request.content_length and request.content_length > MAX_SCREEN_FRAME_BYTES:
            return None, "Frame is too large"
        frame_bytes = request.get_data(cache=False)

    if not frame_bytes:
        return None, "No frame data provided"
    if len(frame_bytes) > MAX_SCREEN_FRAME_BYTES:
        return None, "Frame is too large"
    return frame_bytes, None


@screenshare_bp.route('/api/screenshare/frame', methods=['POST'])
def send_frame():
    chat_manager = chat_routes.chat_manager
    if not chat_manager or not chat_manager.current_room:
        return jsonify({"error": "Not connected to a room"}), 400

    frame_bytes, error = _read_frame_bytes()
    if error:
        status = 413 if error == "Frame is too large" else 400
        return jsonify({"error": error}), status

    try:
        chat_manager.send_screen_frame(frame_bytes)
        return '', 204
    except Exception as e:
        logger.error(f"Error sending screen frame: {e}")
        return jsonify({"error": "Failed to send frame"}), 500

@screenshare_bp.route('/api/screenshare/stop', methods=['POST'])
def stop_share():
    chat_manager = chat_routes.chat_manager
    if not chat_manager:
        return jsonify({"error": "Not connected to chat"}), 400

    try:
        chat_manager.stop_screen_sharing()
        return '', 204
    except Exception as e:
        logger.error(f"Error stopping screen share: {e}")
        return jsonify({"error": "Failed to stop screen share"}), 500
