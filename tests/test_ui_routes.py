import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint, Flask
from PIL import Image

from src.routes import ui_routes as ui_routes_module
from src.routes.ui_routes import init_ui_routes, ui_bp


def image_bytes(format_name, color=(32, 64, 96)):
    payload = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(payload, format=format_name)
    return payload.getvalue()


def animated_image_bytes(format_name):
    payload = io.BytesIO()
    first = Image.new("RGB", (4, 3), (220, 20, 20))
    second = Image.new("RGB", (4, 3), (20, 20, 220))
    first.save(
        payload,
        format=format_name,
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    return payload.getvalue()


JPEG_BYTES = image_bytes("JPEG")
PNG_BYTES = image_bytes("PNG")
WEBP_BYTES = image_bytes("WEBP")


def active_background_path(folder):
    folder = Path(folder)
    marker = folder / ui_routes_module.BACKGROUND_ACTIVE_MARKER
    return folder / marker.read_text(encoding="ascii").strip()


class MutableResourceConfig:
    def __init__(self, config_file, folder):
        self.config_file = str(config_file)
        self.folder = folder

    def get(self, section, option, fallback=None):
        if (section, option) == ("Application", "resourcefolder"):
            return self.folder
        return fallback


class BackgroundRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.resource_folder = Path(self.temporary_directory.name) / "resources"
        self.previous_config = ui_routes_module.config
        self.previous_resource_folder = ui_routes_module.resource_folder
        init_ui_routes(object(), str(self.resource_folder))

        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="background-test-secret")
        self.app.register_blueprint(ui_bp)
        self.client = self.app.test_client()

    def tearDown(self):
        init_ui_routes(self.previous_config, self.previous_resource_folder)
        self.temporary_directory.cleanup()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["profile"] = {"id": "background-user", "email": "user@example.com"}

    def upload(self, payload=JPEG_BYTES, filename="background.jpg", mimetype=None):
        file_value = (io.BytesIO(payload), filename, mimetype) if mimetype else (
            io.BytesIO(payload),
            filename,
        )
        return self.client.post(
            "/change_background",
            data={"backgroundImage": file_value},
            content_type="multipart/form-data",
        )

    def assert_served_background(self, expected_bytes, expected_mimetype, url="/resources/background"):
        response = self.client.get(url)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, expected_bytes)
            self.assertEqual(response.mimetype, expected_mimetype)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        finally:
            response.close()

    def test_supported_static_formats_are_saved_and_served_natively(self):
        self.sign_in()
        cases = (
            ("BACKGROUND.JPG", JPEG_BYTES, "jpg", "image/jpeg"),
            ("background.JPEG", JPEG_BYTES, "jpg", "image/jpeg"),
            ("wallpaper.PNG", PNG_BYTES, "png", "image/png"),
            ("wallpaper.WEBP", WEBP_BYTES, "webp", "image/webp"),
        )

        for filename, payload, canonical_extension, mimetype in cases:
            with self.subTest(filename=filename):
                response = self.upload(
                    payload,
                    filename,
                    mimetype="application/octet-stream",
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {
                    "ok": True,
                    "url": "/resources/background",
                })
                active_path = active_background_path(self.resource_folder)
                self.assertRegex(
                    active_path.name,
                    rf"^background-[0-9a-f]{{16}}\.{canonical_extension}$",
                )
                self.assertEqual(active_path.read_bytes(), payload)
                self.assert_served_background(payload, mimetype)
                self.assert_served_background(payload, mimetype, "/resources/bg.jpg")

    def test_existing_jpg_and_invalid_marker_fall_back_without_migration(self):
        self.sign_in()
        self.resource_folder.mkdir(parents=True)
        existing = image_bytes("JPEG", (96, 64, 32))
        legacy_path = self.resource_folder / "bg.jpg"
        legacy_path.write_bytes(existing)

        self.assert_served_background(existing, "image/jpeg")
        (self.resource_folder / ui_routes_module.BACKGROUND_ACTIVE_MARKER).write_text(
            "../../private.jpg",
            encoding="ascii",
        )
        self.assert_served_background(existing, "image/jpeg", "/resources/bg.jpg")
        self.assertEqual(legacy_path.read_bytes(), existing)

    def test_invalid_uploads_do_not_replace_the_existing_background(self):
        self.sign_in()
        initial = self.upload(image_bytes("JPEG", (96, 64, 32)), "initial.jpg")
        self.assertEqual(initial.status_code, 200)
        existing = active_background_path(self.resource_folder).read_bytes()

        cases = (
            (JPEG_BYTES, "background.gif", "must use"),
            (JPEG_BYTES, "background.svg", "must use"),
            (PNG_BYTES, "background.jpg", "do not match"),
            (b"\xff\xd8\xfftruncated-jpeg", "background.jpg", "not a valid"),
            (b"\x89PNG\r\n\x1a\ntruncated", "background.png", "not a valid"),
            (b"RIFF\x08\x00\x00\x00WEBPbad!", "background.webp", "not a valid"),
        )
        for payload, filename, message in cases:
            with self.subTest(filename=filename, payload=payload[:12]):
                response = self.upload(payload, filename)
                self.assertEqual(response.status_code, 415)
                self.assertIn(message, response.get_json()["error"])
                self.assert_served_background(existing, "image/jpeg")

    def test_animated_png_and_webp_are_rejected(self):
        self.sign_in()
        for format_name, filename in (("PNG", "animated.png"), ("WEBP", "animated.webp")):
            with self.subTest(format=format_name):
                response = self.upload(animated_image_bytes(format_name), filename)
                self.assertEqual(response.status_code, 415)
                self.assertIn("Animated", response.get_json()["error"])

        self.assertFalse(
            (self.resource_folder / ui_routes_module.BACKGROUND_ACTIVE_MARKER).exists()
        )

    def test_missing_and_oversized_uploads_return_real_errors(self):
        self.sign_in()

        missing = self.client.post("/change_background", data={})
        with patch.object(ui_routes_module, "MAX_BACKGROUND_BYTES", 4):
            oversized = self.upload(payload=JPEG_BYTES)

        self.assertEqual(missing.status_code, 400)
        self.assertFalse(missing.get_json()["ok"])
        self.assertEqual(oversized.status_code, 413)
        self.assertFalse(oversized.get_json()["ok"])
        self.assertFalse(
            (self.resource_folder / ui_routes_module.BACKGROUND_ACTIVE_MARKER).exists()
        )

    def test_multipart_request_limit_is_checked_before_file_parsing(self):
        self.sign_in()
        with patch.object(ui_routes_module, "MAX_BACKGROUND_REQUEST_BYTES", 64):
            response = self.client.post(
                "/change_background",
                data=b"x" * 65,
                content_type="application/octet-stream",
            )

        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.get_json()["ok"])

    def test_excessive_dimensions_in_each_format_do_not_replace_the_background(self):
        self.sign_in()
        existing = image_bytes("JPEG", (12, 34, 56))
        self.resource_folder.mkdir(parents=True)
        (self.resource_folder / "bg.jpg").write_bytes(existing)

        cases = (
            (JPEG_BYTES, "background.jpg"),
            (PNG_BYTES, "background.png"),
            (WEBP_BYTES, "background.webp"),
        )
        with patch.object(ui_routes_module, "MAX_BACKGROUND_PIXELS", 1):
            for payload, filename in cases:
                with self.subTest(filename=filename):
                    response = self.upload(payload, filename)
                    self.assertEqual(response.status_code, 415)
                    self.assertIn("dimensions are too large", response.get_json()["error"])

        self.assert_served_background(existing, "image/jpeg")

    def test_marker_publication_failure_preserves_the_previous_background(self):
        self.sign_in()
        self.resource_folder.mkdir(parents=True)
        existing = image_bytes("JPEG", (12, 34, 56))
        (self.resource_folder / "bg.jpg").write_bytes(existing)
        real_replace = os.replace

        def fail_marker_replace(source, destination):
            if Path(destination).name == ui_routes_module.BACKGROUND_ACTIVE_MARKER:
                raise OSError("injected marker failure")
            return real_replace(source, destination)

        with patch.object(ui_routes_module.os, "replace", side_effect=fail_marker_replace):
            response = self.upload(PNG_BYTES, "new.png")

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.assert_served_background(existing, "image/jpeg")
        managed_files = [
            path for path in self.resource_folder.iterdir()
            if ui_routes_module.BACKGROUND_MANAGED_FILE.fullmatch(path.name)
        ]
        self.assertEqual(managed_files, [])

    def test_cleanup_failure_does_not_turn_a_committed_upload_into_an_error(self):
        self.sign_in()
        with patch.object(ui_routes_module.os, "listdir", side_effect=OSError("injected")):
            response = self.upload(PNG_BYTES, "new.png")

        self.assertEqual(response.status_code, 200)
        self.assert_served_background(PNG_BYTES, "image/png")

    def test_background_routes_require_an_authenticated_session(self):
        upload_response = self.upload()
        stable_response = self.client.get("/resources/background")
        legacy_response = self.client.get("/resources/bg.jpg")

        self.assertEqual(upload_response.status_code, 401)
        self.assertEqual(upload_response.get_json()["ok"], False)
        self.assertEqual(stable_response.status_code, 401)
        self.assertEqual(legacy_response.status_code, 401)
        self.assertFalse(self.resource_folder.exists())

    def test_resource_route_does_not_expose_other_files(self):
        self.sign_in()
        self.resource_folder.mkdir(parents=True)
        (self.resource_folder / "private.txt").write_text("private", encoding="utf-8")
        (self.resource_folder / "background-deadbeefdeadbeef.png").write_bytes(PNG_BYTES)

        for filename in ("private.txt", "background-deadbeefdeadbeef.png", ".background-active"):
            with self.subTest(filename=filename):
                response = self.client.get(f"/resources/{filename}")
                self.assertEqual(response.status_code, 404)

    def test_background_activation_never_serves_or_deletes_sibling_downloads(self):
        self.sign_in()
        download_folder = Path(self.temporary_directory.name) / "downloads"
        background_folder = download_folder / "backgrounds"
        download_folder.mkdir()
        downloads = {
            "bg.jpg": b"downloaded-jpg",
            "bg.png": b"downloaded-png",
            "background-deadbeefdeadbeef.webp": b"downloaded-webp",
        }
        for filename, contents in downloads.items():
            (download_folder / filename).write_bytes(contents)
        init_ui_routes(object(), str(background_folder))

        response = self.upload(PNG_BYTES, "selected-background.png")

        self.assertEqual(response.status_code, 200)
        self.assert_served_background(PNG_BYTES, "image/png")
        for filename, contents in downloads.items():
            with self.subTest(filename=filename):
                self.assertEqual((download_folder / filename).read_bytes(), contents)

    def test_relative_resource_folder_tracks_the_current_application_setting(self):
        self.sign_in()
        config_root = Path(self.temporary_directory.name) / "config"
        config_root.mkdir()
        mutable_config = MutableResourceConfig(config_root / "config.ini", "appearance")
        init_ui_routes(mutable_config, "ignored")

        first_response = self.upload(payload=JPEG_BYTES)
        first_active = active_background_path(config_root / "appearance")
        mutable_config.folder = "other-appearance"
        second_image = image_bytes("PNG", (120, 80, 40))
        second_response = self.upload(payload=second_image, filename="background.png")
        second_active = active_background_path(config_root / "other-appearance")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_active.read_bytes(), JPEG_BYTES)
        self.assertEqual(second_active.read_bytes(), second_image)

    def test_background_form_feedback_is_available_on_shared_settings_pages(self):
        sites_folder = Path(__file__).resolve().parents[1] / "sites"
        template_folder = sites_folder / "templates"
        accepted_types = (
            'accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"'
        )
        template = (template_folder / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="backgroundStatus"', template)
        self.assertIn(accepted_types, template)
        self.assertIn("Static images only", template)

        project_template = (template_folder / "project_manager.html").read_text(encoding="utf-8")
        project_css = (sites_folder / "static" / "css" / "project_manager.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("js/settings.js", project_template)
        self.assertIn("--kasugai-background-image", project_css)


class TeamRoomNavigationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="team-room-route-test-secret")

        auth_bp = Blueprint("auth_bp", __name__)
        auth_bp.add_url_rule("/login", "login", lambda: "login")
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(ui_bp)
        self.client = self.app.test_client()

    def sign_in(self):
        with self.client.session_transaction() as session:
            session["profile"] = {
                "id": "team-room-user",
                "email": "team-room@example.com",
            }

    def test_team_room_route_opens_the_shared_drawer_on_home(self):
        self.sign_in()

        response = self.client.get("/team-room")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/?team_room=open")

    def test_legacy_screenshare_route_deep_links_to_the_shared_drawer(self):
        self.sign_in()

        response = self.client.get("/screenshare")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "/?team_room=open&screen=expanded",
        )

    def test_team_room_routes_require_a_signed_in_session(self):
        for route in ("/team-room", "/screenshare"):
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["Location"], "/login")

    def test_home_and_projects_use_one_shared_team_room_surface(self):
        sites_folder = Path(__file__).resolve().parents[1] / "sites"
        template_folder = sites_folder / "templates"
        home = (template_folder / "index.html").read_text(encoding="utf-8")
        projects = (template_folder / "project_manager.html").read_text(encoding="utf-8")
        team_room = (template_folder / "_team_room.html").read_text(encoding="utf-8")

        for name, template in (("home", home), ("projects", projects)):
            with self.subTest(template=name):
                self.assertIn("{% include '_team_room.html' %}", template)
                self.assertIn("js/team_room.js", template)
                self.assertIn("data-team-room-trigger", template)
                self.assertIn("data-team-room-activity", template)
                self.assertNotIn("ui_bp.screen_share", template)

        self.assertEqual(team_room.count('id="teamRoomDrawer"'), 1)
        self.assertIn('id="chatForm"', team_room)
        self.assertIn('id="sendFileForm"', team_room)
        self.assertIn('id="screenShareStage"', team_room)
        self.assertNotIn('id="chatModal"', team_room)
        self.assertNotIn('id="fileTransferModal"', team_room)
        self.assertNotIn('role="tablist"', team_room)
        self.assertIn('id="fileComposer"', team_room)
        self.assertIn('id="startScreenShareBtn"', team_room)


if __name__ == "__main__":
    unittest.main()
