# routes/ui_routes.py
import os
from flask import Blueprint, render_template, request, redirect, url_for, send_from_directory, session, jsonify
from werkzeug.utils import secure_filename
from src.global_logger import GlobalLogger

ui_bp = Blueprint('ui_bp', __name__)
logger = GlobalLogger.get_logger("UIRoutes")

config = None
upload_folder = None

def init_ui_routes(cfg, folder):
    global config, upload_folder
    config = cfg
    upload_folder = folder

@ui_bp.route('/')
def index():
    if 'profile' not in session:
        return redirect(url_for('auth_bp.login'))

    buttons_string = config.get('Application', 'buttons')
    buttons = [item.split(':')[0].strip() for item in buttons_string.split(',')]
    return render_template('index.html', buttons=buttons, user=session['profile'])

@ui_bp.route('/resources/<path:filename>')
def serve_resources(filename):
    full_path = os.path.join(os.path.expanduser('~'), 'kasugai', 'resources')
    return send_from_directory(full_path, filename)

@ui_bp.route('/change_background', methods=['POST'])
def change_background():
    if 'backgroundImage' in request.files:
        file = request.files['backgroundImage']
        if file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(upload_folder, 'bg.jpg'))
    return redirect(url_for('ui_bp.index'))

@ui_bp.route('/screenshare')
def screen_share():
    if 'profile' not in session:
        return redirect(url_for('auth_bp.login'))
    buttons_string = config.get('Application', 'buttons')
    buttons = [item.split(':')[0].strip() for item in buttons_string.split(',')]
    return render_template('screenshare.html', buttons=buttons, user=session['profile'])

@ui_bp.route('/open_network_settings', methods=['POST'])
def open_network_settings():
    try:
        from network_settings import launch_network_settings
        launch_network_settings()
        return '', 204  # ✅ No Content = no page update or body render
    except Exception as e:
        logger.error(f"Failed to launch network settings: {e}")
        return jsonify({"error": "Failed to launch network settings"}), 500
