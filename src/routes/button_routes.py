# routes/button_routes.py
from flask import Blueprint, request, jsonify
from src.global_logger import GlobalLogger
from src.button_manager import ButtonManager

button_bp = Blueprint('button_bp', __name__)
logger = GlobalLogger.get_logger("ButtonRoutes")

button_manager = None  # Will be set from WebServer

def init_button_routes(cfg):
    global button_manager
    button_manager = ButtonManager()

@button_bp.route('/api/buttons', methods=['GET'])
def list_buttons():
    return jsonify(button_manager.get_buttons()), 200

@button_bp.route('/api/buttons', methods=['POST'])
def add_button():
    data = request.get_json(silent=True) or request.form
    name = data.get('name')
    link = data.get('link')

    if not name or not link:
        return jsonify({"error": "Button name and link/filepath are both required"}), 400

    try:
        buttons = button_manager.add_button(name, link)
        return jsonify(buttons), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error(f"Error adding button: {e}")
        return jsonify({"error": "Failed to add button"}), 500

@button_bp.route('/api/buttons/<button_name>', methods=['DELETE'])
def remove_button(button_name):
    try:
        buttons = button_manager.remove_button(button_name)
        return jsonify(buttons), 200
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error removing button: {e}")
        return jsonify({"error": "Failed to remove button"}), 500

@button_bp.route('/button_click/<button_name>', methods=['POST'])
def button_click(button_name):
    link = button_manager.get_link(button_name)
    if link is None:
        return jsonify({"error": "Button not found"}), 404

    # Opening a URL on the web-server host is surprising in native mode and
    # meaningless in Docker. The browser owns bookmarks; local execution uses
    # the separately paired, locally allowlisted launcher companion.
    return jsonify({
        "error": "Open this HTTPS shortcut in the browser; use Launcher for local tasks",
        "url": link,
    }), 410
