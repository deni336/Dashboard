# routes/file_routes.py
from flask import Blueprint, request, jsonify
from file_manager import FileManager
from global_logger import GlobalLogger

file_bp = Blueprint('file_bp', __name__)
logger = GlobalLogger.get_logger("FileRoutes")
file_manager = FileManager()

@file_bp.route('/api/files', methods=['GET'])
def get_files():
    try:
        return jsonify(file_manager.get_available_files()), 200
    except Exception as e:
        logger.error(f"Error fetching file list: {e}")
        return jsonify({"error": "Failed to retrieve files"}), 500

@file_bp.route('/api/files', methods=['POST'])
def stage_file():
    try:
        data = request.get_json()
        ip = data.get('ip')
        size = data.get('size')
        path = data.get('path')
        if not all([ip, size, path]):
            return jsonify({"error": "Missing required fields"}), 400
        file_manager.stage(ip, size, path)
        return jsonify({'message': 'File staged successfully'}), 201
    except Exception as e:
        logger.error(f"Error staging file: {e}")
        return jsonify({"error": "Failed to stage file"}), 500

@file_bp.route('/api/files/<filename>', methods=['DELETE'])
def delete_file(filename):
    try:
        file_manager.delete(filename)
        return jsonify({'message': f'{filename} deleted from list'}), 200
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return jsonify({"error": "Failed to delete file"}), 500
