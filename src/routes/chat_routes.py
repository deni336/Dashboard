# routes/chat_routes.py
from flask import Blueprint, request, jsonify
from src.global_logger import GlobalLogger

chat_bp = Blueprint('chat_bp', __name__)
logger = GlobalLogger.get_logger("ChatRoutes")

# This will be injected from WebServer
chat_manager = None
rooms = {}

def init_chat_routes(cm, registered_rooms):
    global chat_manager, rooms
    chat_manager = cm
    rooms = registered_rooms

@chat_bp.route('/send_message', methods=['POST'])
def send_message():
    try:
        message = request.form.get('message')
        if not message:
            return jsonify({'error': 'Message content is missing'}), 400
        chat_manager.send_message(message)
        return jsonify({'status': 'Message sent successfully'}), 200
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({'error': str(e)}), 500

@chat_bp.route('/join_room', methods=['POST'])
def join_room():
    data = request.get_json()
    room = data.get('room')
    password = data.get('password')

    if room and room in rooms:
        chat_manager.join_room(room, password)
        return jsonify({"message": f"Joined room: {room}"}), 200
    else:
        return jsonify({"error": "Room not found"}), 404

@chat_bp.route('/create_room', methods=['POST'])
def create_room():
    data = request.get_json()
    room_name = data.get('roomName')
    room_password = data.get('roomPassword', '')

    if not room_name:
        return jsonify({'error': 'Room name required'}), 400

    try:
        new_room = chat_manager.create_room(room_name, room_password)

        # ✅ Update global/shared `rooms` dict with the new room
        rooms[new_room['id']] = new_room

        return jsonify({'status': 'Room created', 'room': new_room}), 200
    except Exception as e:
        logger.error(f"Failed to create room: {e}")
        return jsonify({'error': str(e)}), 500
