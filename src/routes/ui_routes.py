# routes/ui_routes.py
import io
import os
import re
import secrets
import threading

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge

from src.global_logger import GlobalLogger
from src.button_manager import ButtonManager

button_manager = ButtonManager()

ui_bp = Blueprint('ui_bp', __name__)
logger = GlobalLogger.get_logger("UIRoutes")

config = None
resource_folder = None

BACKGROUND_RESOURCE_NAME = 'background'
BACKGROUND_LEGACY_ALIAS = 'bg.jpg'
BACKGROUND_ACTIVE_MARKER = '.background-active'
BACKGROUND_FORMATS = {
    '.jpg': ('JPEG', '.jpg'),
    '.jpeg': ('JPEG', '.jpg'),
    '.png': ('PNG', '.png'),
    '.webp': ('WEBP', '.webp'),
}
BACKGROUND_MIME_TYPES = {
    '.jpg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}
BACKGROUND_MANAGED_FILE = re.compile(
    r'^background-[0-9a-f]{16}\.(?:jpg|png|webp)$'
)
# Before native-format support Kasugai wrote only this one fixed JPEG name.
BACKGROUND_LEGACY_FILES = ('bg.jpg',)
MAX_BACKGROUND_BYTES = 20 * 1024 * 1024
MAX_BACKGROUND_REQUEST_BYTES = MAX_BACKGROUND_BYTES + (1024 * 1024)
MAX_BACKGROUND_PIXELS = 40_000_000
background_file_lock = threading.Lock()


class BackgroundValidationError(ValueError):
    """A safe validation message that can be returned to the upload client."""


def _resource_folder():
    configured_folder = resource_folder
    get_config = getattr(config, 'get', None)
    if callable(get_config):
        configured_folder = get_config(
            'Application',
            'resourcefolder',
            fallback=configured_folder,
        )
    if not configured_folder:
        raise RuntimeError('The resource folder is not configured')
    configured_folder = os.path.expanduser(configured_folder)
    if os.path.isabs(configured_folder):
        return os.path.abspath(configured_folder)

    config_file = getattr(config, 'config_file', '')
    base_folder = (
        os.path.dirname(os.path.abspath(os.path.expanduser(config_file)))
        if config_file
        else os.getcwd()
    )
    return os.path.abspath(os.path.join(base_folder, configured_folder))


def _background_error(message, status):
    return jsonify({'ok': False, 'error': message}), status


def _active_background_filename(folder):
    marker_path = os.path.join(folder, BACKGROUND_ACTIVE_MARKER)
    try:
        with open(marker_path, encoding='ascii') as marker_file:
            active_filename = marker_file.read(128).strip()
        if (
            BACKGROUND_MANAGED_FILE.fullmatch(active_filename)
            and os.path.isfile(os.path.join(folder, active_filename))
            and not os.path.islink(os.path.join(folder, active_filename))
        ):
            return active_filename
    except (OSError, UnicodeError):
        pass

    for legacy_filename in BACKGROUND_LEGACY_FILES:
        legacy_path = os.path.join(folder, legacy_filename)
        if os.path.isfile(legacy_path) and not os.path.islink(legacy_path):
            return legacy_filename
    return None


def _validate_background_image(image_bytes, expected_format):
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format != expected_format:
                raise BackgroundValidationError(
                    'The file contents do not match the selected image type.'
                )
            if getattr(image, 'n_frames', 1) != 1:
                raise BackgroundValidationError(
                    'Animated background images are not supported.'
                )
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_BACKGROUND_PIXELS:
                raise BackgroundValidationError(
                    'The background image dimensions are too large; use at most 40 megapixels.'
                )
            image.verify()
        # verify() checks the container. Reopen and decode every pixel so a
        # truncated scan cannot replace the last known-good background.
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
    except BackgroundValidationError:
        raise
    except (
        Image.DecompressionBombError,
        EOFError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise BackgroundValidationError(
            'The selected file is not a valid JPG, PNG, or WebP image.'
        ) from exc


def _activate_background_image(folder, image_bytes, canonical_extension):
    os.makedirs(folder, exist_ok=True)
    token = secrets.token_hex(8)
    active_filename = f'background-{token}{canonical_extension}'
    active_path = os.path.join(folder, active_filename)
    image_temporary_path = os.path.join(folder, f'.{active_filename}.tmp')
    marker_path = os.path.join(folder, BACKGROUND_ACTIVE_MARKER)
    marker_temporary_path = os.path.join(folder, f'{BACKGROUND_ACTIVE_MARKER}.{token}.tmp')
    image_published = False
    marker_published = False

    with background_file_lock:
        previous_filename = _active_background_filename(folder)
        try:
            with open(image_temporary_path, 'xb') as background_file:
                background_file.write(image_bytes)
            os.chmod(image_temporary_path, 0o600)
            with open(marker_temporary_path, 'x', encoding='ascii') as marker_file:
                marker_file.write(active_filename)
            os.chmod(marker_temporary_path, 0o600)

            os.replace(image_temporary_path, active_path)
            image_published = True
            os.replace(marker_temporary_path, marker_path)
            marker_published = True

            preserved_files = {active_filename, previous_filename}
            try:
                existing_filenames = os.listdir(folder)
            except OSError:
                logger.warning(
                    'Could not inspect the background folder for superseded files',
                    exc_info=True,
                )
                existing_filenames = ()
            for existing_filename in existing_filenames:
                if existing_filename in preserved_files:
                    continue
                if (
                    BACKGROUND_MANAGED_FILE.fullmatch(existing_filename)
                ):
                    try:
                        os.remove(os.path.join(folder, existing_filename))
                    except OSError:
                        logger.warning(
                            'Could not remove superseded background file %s',
                            existing_filename,
                        )
        finally:
            for temporary_path in (image_temporary_path, marker_temporary_path):
                if os.path.exists(temporary_path):
                    try:
                        os.remove(temporary_path)
                    except OSError:
                        logger.warning(
                            'Could not remove temporary background file %s',
                            temporary_path,
                        )
            if image_published and not marker_published and os.path.exists(active_path):
                try:
                    os.remove(active_path)
                except OSError:
                    logger.warning('Could not remove uncommitted background file %s', active_path)

    return active_filename


def init_ui_routes(cfg, folder):
    global config, resource_folder
    config = cfg
    resource_folder = folder


@ui_bp.route('/')
def index():
    if 'profile' not in session:
        return redirect(url_for('auth_bp.login'))

    buttons = [b['name'] for b in button_manager.get_buttons()]
    csrf_token = session.get("csrf_token")
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session["csrf_token"] = csrf_token
    return render_template(
        'index.html',
        buttons=buttons,
        user=session['profile'],
        current_user_id=session.get('kasugai_user_id', ''),
        csrf_token=csrf_token,
    )


@ui_bp.route('/resources/<path:filename>')
def serve_resources(filename):
    if 'profile' not in session:
        abort(401)
    if filename not in {BACKGROUND_RESOURCE_NAME, BACKGROUND_LEGACY_ALIAS}:
        abort(404)
    try:
        folder = _resource_folder()
        with background_file_lock:
            active_filename = _active_background_filename(folder)
            if not active_filename:
                abort(404)
            extension = os.path.splitext(active_filename)[1].lower()
            mimetype = BACKGROUND_MIME_TYPES.get(extension)
            if not mimetype:
                abort(404)
            # Keep the lock until Flask has opened the selected generation.
            # A concurrent upload can then safely retire older generations.
            response = send_from_directory(
                folder,
                active_filename,
                conditional=True,
                max_age=0,
                mimetype=mimetype,
            )
    except RuntimeError:
        logger.exception('The background resource folder is not configured')
        abort(503)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@ui_bp.route('/change_background', methods=['POST'])
def change_background():
    if 'profile' not in session:
        return _background_error('Sign in before changing the background.', 401)

    request.max_content_length = MAX_BACKGROUND_REQUEST_BYTES
    request.max_form_parts = 4
    if request.content_length and request.content_length > MAX_BACKGROUND_REQUEST_BYTES:
        return _background_error('The background upload request is too large.', 413)
    try:
        file = request.files.get('backgroundImage')
    except RequestEntityTooLarge:
        return _background_error('The background upload request is too large.', 413)
    if file is None or not file.filename:
        return _background_error('Choose a JPG, PNG, or WebP image to upload.', 400)

    extension = os.path.splitext(file.filename)[1].lower()
    format_details = BACKGROUND_FORMATS.get(extension)
    if not format_details:
        return _background_error(
            'Background images must use a .jpg, .jpeg, .png, or .webp extension.',
            415,
        )
    expected_format, canonical_extension = format_details

    image_bytes = file.read(MAX_BACKGROUND_BYTES + 1)
    if len(image_bytes) > MAX_BACKGROUND_BYTES:
        return _background_error('The background image must be 20 MB or smaller.', 413)
    try:
        _validate_background_image(image_bytes, expected_format)
    except BackgroundValidationError as exc:
        return _background_error(str(exc), 415)

    try:
        _activate_background_image(
            _resource_folder(),
            image_bytes,
            canonical_extension,
        )
    except (OSError, RuntimeError):
        logger.exception('Failed to save the uploaded background image')
        return _background_error('Kasugai could not save the background image.', 500)

    return jsonify({
        'ok': True,
        'url': url_for('ui_bp.serve_resources', filename=BACKGROUND_RESOURCE_NAME),
    })


@ui_bp.route('/team-room')
def team_room():
    if 'profile' not in session:
        return redirect(url_for('auth_bp.login'))
    return redirect(url_for('ui_bp.index', team_room='open'))


@ui_bp.route('/screenshare')
def screen_share():
    if 'profile' not in session:
        return redirect(url_for('auth_bp.login'))
    return redirect(
        url_for('ui_bp.index', team_room='open', screen='expanded')
    )
