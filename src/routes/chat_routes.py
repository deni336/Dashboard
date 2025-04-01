# routes/chat_routes.py
from flask import Blueprint, request, jsonify
from global_logger import GlobalLogger

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
    room = data.get('room')
    password = data.get('password')

    if room:
        if room in rooms:
            return jsonify({"Error": "Room already exists"}), 400
        else:
            rooms[room] = {"password": password}
            return jsonify({"Message": f"Room '{room}' created successfully"}), 200
    else:
        return jsonify({"Error": "Room name is required"}), 400
