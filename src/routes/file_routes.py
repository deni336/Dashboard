# routes/file_routes.py
import os
import tempfile
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from src.file_manager import FileManager
from src.global_logger import GlobalLogger
import src.routes.chat_routes as chat_routes

file_bp = Blueprint('file_bp', __name__)
logger = GlobalLogger.get_logger("FileRoutes")
file_manager = FileManager()
MAX_FILE_TRANSFER_BYTES = 100 * 1024 * 1024


def _get_chat_manager():
    chat_manager = chat_routes.chat_manager
    if not chat_manager or not chat_manager.user:
        return None
    return chat_manager


def _current_user_id(chat_manager):
    return chat_manager.user.id.uuid


def _is_allowed_file_user(metadata, user_id):
    return (
        metadata.senderId and metadata.senderId.uuid == user_id
        or metadata.recipientId and metadata.recipientId.uuid == user_id
    )

@file_bp.route('/api/files/send', methods=['POST'])
def send_file():
    chat_manager = _get_chat_manager()
    if not chat_manager:
        return jsonify({"error": "Not connected to chat"}), 400
    if not chat_manager.current_room:
        return jsonify({"error": "Join or create a room before sending files"}), 400
    if request.content_length and request.content_length > MAX_FILE_TRANSFER_BYTES:
        return jsonify({"error": "File is too large"}), 413

    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"error": "No file selected"}), 400

    recipient_id = request.form.get('recipient_id')
    if not recipient_id:
        return jsonify({"error": "recipient_id is required"}), 400
    participants = {p["id"] for p in chat_manager.list_participants()}
    if recipient_id not in participants:
        return jsonify({"error": "Recipient is not in the current room"}), 400

    file = request.files['file']
    filename = secure_filename(file.filename) or "upload.bin"
    mime_type = file.mimetype or "application/octet-stream"

    with tempfile.TemporaryDirectory(prefix='kasugai_upload_') as tmp_dir:
        tmp_path = os.path.join(tmp_dir, filename)
        file.save(tmp_path)
        file_size = os.path.getsize(tmp_path)
        if file_size > MAX_FILE_TRANSFER_BYTES:
            return jsonify({"error": "File is too large"}), 413

        try:
            file_id = file_manager.send_file(
                tmp_path,
                sender_id=_current_user_id(chat_manager),
                recipient_id=recipient_id
            )
            chat_manager.send_file_offer(recipient_id, file_id, filename, file_size, mime_type)
            return jsonify({
                "file_id": file_id,
                "name": filename,
                "size": file_size,
                "mime_type": mime_type,
                "recipient_id": recipient_id,
            }), 201
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            return jsonify({"error": "Failed to send file"}), 500

@file_bp.route('/api/files/offers', methods=['GET'])
def list_file_offers():
    chat_manager = _get_chat_manager()
    if not chat_manager:
        return jsonify([]), 200

    return jsonify(chat_manager.get_pending_file_offers()), 200

@file_bp.route('/api/files/<file_id>/download', methods=['GET'])
def download_file(file_id):
    chat_manager = _get_chat_manager()
    if not chat_manager:
        return jsonify({"error": "Not connected to chat"}), 400

    try:
        metadata = file_manager.get_metadata(file_id)
        user_id = _current_user_id(chat_manager)
        if not _is_allowed_file_user(metadata, user_id):
            return jsonify({"error": "You are not allowed to download this file"}), 403

        destination_path = file_manager.download(file_id, metadata=metadata)
        if metadata.recipientId and metadata.recipientId.uuid == user_id:
            chat_manager.mark_file_offer_downloaded(file_id)

        return send_file(
            destination_path,
            as_attachment=True,
            download_name=metadata.name or os.path.basename(destination_path),
            mimetype=metadata.mimeType or "application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return jsonify({"error": "Failed to download file"}), 500

@file_bp.route('/api/files/<file_id>/offer', methods=['DELETE'])
def dismiss_file_offer(file_id):
    chat_manager = _get_chat_manager()
    if not chat_manager:
        return '', 204

    chat_manager.mark_file_offer_downloaded(file_id)
    return '', 204
