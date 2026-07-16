# routes/chat_routes.py
from flask import Blueprint, request, jsonify
from src.global_logger import GlobalLogger

chat_bp = Blueprint('chat_bp', __name__)
logger = GlobalLogger.get_logger("ChatRoutes")

# This will be injected from WebServer
chat_manager = None
rooms = {}


def _current_chat_manager():
    return chat_manager


def _room_summaries():
    summaries = []
    for room_id, room in rooms.items():
        if isinstance(room, dict):
            name = room.get('name') or room_id
            room_type = room.get('type') or 'CHAT'
        else:
            name = getattr(room, 'name', None) or room_id
            room_type = getattr(room, 'type', None) or 'CHAT'
        summaries.append({
            'id': str(room_id),
            'name': str(name),
            'type': str(room_type),
        })
    return sorted(summaries, key=lambda room: room['name'].casefold())

def init_chat_routes(cm, registered_rooms):
    global chat_manager, rooms
    chat_manager = cm
    rooms = registered_rooms

@chat_bp.route('/send_message', methods=['POST'])
def send_message():
    try:
        manager = _current_chat_manager()
        if not manager or not manager.current_room:
            return jsonify({'error': 'Join or create a room before sending messages.'}), 409
        message = request.form.get('message')
        if not message:
            return jsonify({'error': 'Message content is missing'}), 400
        if not manager.send_message(message):
            return jsonify({'error': 'Kasugai could not send the message.'}), 502
        return jsonify({'status': 'Message sent successfully'}), 200
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({'error': str(e)}), 500

@chat_bp.route('/join_room', methods=['POST'])
def join_room():
    manager = _current_chat_manager()
    if not manager:
        return jsonify({'error': 'Chat is not connected.'}), 503
    data = request.get_json(silent=True) or {}
    room = data.get('room')
    password = data.get('password')

    if room and room in rooms:
        if not manager.join_room(room, password or ''):
            return jsonify({'error': 'Unable to join that room. Check its password.'}), 403
        return jsonify({"message": f"Joined room: {room}"}), 200
    else:
        return jsonify({"error": "Room not found"}), 404

@chat_bp.route('/api/room/participants', methods=['GET'])
def get_room_participants():
    manager = _current_chat_manager()
    if not manager or not manager.current_room:
        return jsonify([]), 200
    return jsonify(manager.list_participants()), 200


@chat_bp.route('/api/rooms', methods=['GET'])
def list_rooms():
    manager = _current_chat_manager()
    return jsonify({
        'rooms': _room_summaries(),
        'current_room': str(manager.current_room) if manager and manager.current_room else '',
    }), 200

@chat_bp.route('/create_room', methods=['POST'])
def create_room():
    manager = _current_chat_manager()
    if not manager:
        return jsonify({'error': 'Chat is not connected.'}), 503
    data = request.get_json(silent=True) or {}
    room_name = data.get('roomName')
    room_password = data.get('roomPassword', '')

    if not room_name:
        return jsonify({'error': 'Room name required'}), 400

    try:
        new_room = manager.create_room(room_name, room_password)

        if not new_room or 'id' not in new_room:
            logger.error("create_room failed: new_room is None or missing 'id'")
            return jsonify({'error': 'Failed to create room'}), 500

        # ✅ Update shared room list
        rooms[new_room['id']] = new_room

        return jsonify({'status': 'Room created', 'room': new_room}), 200

    except Exception as e:
        logger.error(f"Failed to create room: {e}")
        return jsonify({'error': str(e)}), 500
