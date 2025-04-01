# routes/button_routes.py
import os
import platform
import subprocess
import webbrowser
from flask import Blueprint, request, render_template, session, abort
from src.global_logger import GlobalLogger

button_bp = Blueprint('button_bp', __name__)
logger = GlobalLogger.get_logger("ButtonRoutes")

config = None  # Will be set from WebServer

def init_button_routes(cfg):
    global config
    config = cfg

@button_bp.route('/save_buttons', methods=['POST'])
def save_buttons():
    button_name = request.form['buttonName']
    button_link = request.form['buttonLink']

    # Fetch and append new button
    buttons_string = config.get('Application', 'buttons')
    new_button = f"{button_name}:{button_link}"
    buttons_string = f"{buttons_string},{new_button}" if buttons_string else new_button

    config.set('Application', 'buttons', buttons_string)
    buttons = [item.split(':')[0].strip() for item in buttons_string.split(',')]
    return render_template('index.html', buttons=buttons, user=session['profile'])

@button_bp.route('/button_click/<button_name>', methods=['POST'])
def button_click(button_name):
    buttons_string = config.get('Application', 'buttons')
    buttons = {item.split(':', 1)[0].strip(): item.split(':', 1)[1].strip() for item in buttons_string.split(',')}

    if button_name not in buttons:
        return abort(404, description="Button not found")

    link = buttons[button_name]
    try:
        if link.startswith('http://') or link.startswith('https://'):
            webbrowser.open_new_tab(link)
        elif os.path.exists(link):
            if platform.system() == "Windows":
                os.startfile(link)
            elif platform.system() == "Linux":
                subprocess.Popen(['xdg-open', link])
            elif platform.system() == "Darwin":
                subprocess.Popen(['open', link])
        else:
            return abort(404, description="File not found")
        return '', 204
    except Exception as e:
        logger.error(f"Failed to handle button click for {link}: {e}")
        return abort(500, description="Failed to execute the file.")
