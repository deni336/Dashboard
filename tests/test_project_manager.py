import json
import sqlite3
import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from flask import Blueprint, Flask

from src.project_ai import sign_proposal
from src.project_manager import ProjectStore
from src.routes import project_routes as project_routes_module
from src.routes.project_routes import init_project_routes, project_bp


class FakeConfig:
    def __init__(self, database_path):
        self.values = {
            ("Database", "projectdbpath"): str(database_path),
            ("Database", "encryption_key"): Fernet.generate_key().decode("ascii"),
        }

    def get(self, section, option, fallback=None):
        return self.values.get((section, option), fallback)

    def set(self, section, option, value):
        self.values[(section, option)] = value


def project_values(code="OPS-1"):
    return {
        "name": "Operations rollout",
        "code": code,
        "description": "Restricted project brief",
        "status": "active",
        "priority": "high",
        "health": "at_risk",
        "manager": "Avery Morgan",
        "sponsor": "Jordan Lee",
        "start_date": "2026-07-01",
        "target_date": "2026-09-30",
        "budget": 125000,
        "progress": 35,
    }


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "projects.db"
        self.config = FakeConfig(self.database_path)
        self.store = ProjectStore(self.config)
        self.owner = "owner@example.com"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_personal_openai_keys_are_encrypted_and_isolated_by_user(self):
        first_key = "sk-user-a-personal-key-value"
        second_key = "sk-user-b-personal-key-value"
        replacement_key = "sk-user-a-replacement-key-value"

        first_status = self.store.set_openai_api_key("user-a", first_key)
        second_status = self.store.set_openai_api_key("user-b", second_key)

        self.assertTrue(first_status["personal_key_configured"])
        self.assertNotIn("api_key", first_status)
        self.assertNotIn(first_key, json.dumps(first_status))
        self.assertNotIn(second_key, json.dumps(second_status))
        self.assertEqual(self.store.openai_api_key("user-a"), first_key)
        self.assertEqual(self.store.openai_api_key("user-b"), second_key)

        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = dict(connection.execute(
                "SELECT owner_key, openai_api_key FROM project_user_credentials"
            ).fetchall())
        self.assertTrue(rows["user-a"].startswith("gAAAA"))
        self.assertTrue(rows["user-b"].startswith("gAAAA"))
        self.assertNotIn(first_key, rows["user-a"])
        self.assertNotIn(second_key, rows["user-b"])

        self.store.set_openai_api_key("user-a", replacement_key)
        self.assertEqual(self.store.openai_api_key("user-a"), replacement_key)
        self.assertEqual(self.store.openai_api_key("user-b"), second_key)
        self.store.delete_openai_api_key("user-a")
        self.assertEqual(self.store.openai_api_key("user-a"), "")
        self.assertEqual(self.store.openai_api_key("user-b"), second_key)

    def test_large_ai_audit_payload_is_compacted_as_valid_json(self):
        compacted = self.store._ai_audit_actions([{
            "type": "create_meeting",
            "reason": "Large generated note",
            "record_id": None,
            "evidence_refs": [],
            "fields": {"notes": "x" * 120_000},
        }])

        decoded = json.loads(compacted)
        self.assertTrue(decoded["truncated"])
        self.assertEqual(decoded["action_count"], 1)
        self.assertEqual(decoded["actions"][0]["field_names"], ["notes"])

    def test_full_workspace_lifecycle_and_encrypted_notes(self):
        project = self.store.create_project(self.owner, project_values())
        record = self.store.create_record(self.owner, project["id"], {
            "kind": "risk",
            "title": "Vendor lead time",
            "details": "Supplier schedule is confidential",
            "status": "monitoring",
            "priority": "high",
            "owner": "Casey",
            "due_date": "2026-08-10",
            "resolution": "Keep secondary vendor available",
        })
        meeting = self.store.create_meeting(self.owner, project["id"], {
            "title": "Steering committee",
            "held_on": "2026-07-14",
            "attendees": "Avery, Jordan",
            "notes": "Do not store this sentence as plaintext",
            "decisions": "Continue rollout",
            "action_items": "Casey to confirm capacity",
            "next_steps": "Review next Tuesday",
        })
        stakeholder = self.store.create_stakeholder(self.owner, project["id"], {
            "name": "Taylor Kim",
            "role": "Operations lead",
            "email": "taylor@example.com",
            "influence": "high",
            "engagement": "supportive",
            "notes": "Weekly written update",
        })
        connection = self.store.create_connection(self.owner, {
            "project_id": project["id"],
            "provider": "github",
            "label": "Delivery repository",
            "account": "example/project",
            "url": "https://github.com/example/project",
        })

        workspace = self.store.workspace(self.owner, project["id"])

        self.assertEqual(workspace["project"]["description"], "Restricted project brief")
        self.assertEqual(workspace["records"][0]["id"], record["id"])
        self.assertEqual(workspace["meetings"][0]["notes"], "Do not store this sentence as plaintext")
        self.assertEqual(workspace["stakeholders"][0]["id"], stakeholder["id"])
        self.assertIn(connection["id"], [item["id"] for item in workspace["connections"]])

        with closing(sqlite3.connect(self.database_path)) as connection_db:
            raw_notes = connection_db.execute(
                "SELECT notes FROM project_meetings WHERE id = ?",
                (meeting["id"],),
            ).fetchone()[0]
        self.assertNotIn("plaintext", raw_notes)
        self.assertTrue(raw_notes.startswith("gAAAA"))

        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.workspace("another@example.com", project["id"])

        self.store.delete_project(self.owner, project["id"])
        with closing(sqlite3.connect(self.database_path)) as connection_db:
            child_count = connection_db.execute(
                "SELECT COUNT(*) FROM project_meetings WHERE project_id = ?",
                (project["id"],),
            ).fetchone()[0]
        self.assertEqual(child_count, 0)

    def test_default_connections_are_seeded_only_once(self):
        first = self.store.portfolio(self.owner)
        self.assertEqual(len(first["connections"]), 5)

        for connection in first["connections"]:
            self.store.delete_connection(self.owner, connection["id"])

        second = self.store.portfolio(self.owner)
        self.assertEqual(second["connections"], [])

    def test_update_rejects_dates_that_conflict_with_existing_project(self):
        project = self.store.create_project(self.owner, project_values())

        with self.assertRaisesRegex(ValueError, "target_date cannot be before start_date"):
            self.store.update_project(
                self.owner,
                project["id"],
                {"target_date": "2026-06-30"},
            )

    def test_users_have_private_portfolios_and_independent_project_codes(self):
        first_user = "first-user-id"
        second_user = "second-user-id"
        first_project = self.store.create_project(first_user, project_values("SAME-CODE"))
        second_project = self.store.create_project(second_user, project_values("SAME-CODE"))

        first_portfolio = self.store.portfolio(first_user)
        second_portfolio = self.store.portfolio(second_user)
        self.assertEqual([item["id"] for item in first_portfolio["projects"]], [first_project["id"]])
        self.assertEqual([item["id"] for item in second_portfolio["projects"]], [second_project["id"]])
        self.assertNotIn("owner_key", first_project)
        self.assertNotIn("owner_key", first_portfolio["projects"][0])

        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.workspace(first_user, second_project["id"])
        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.update_project(second_user, first_project["id"], {"progress": 90})
        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.delete_project(first_user, second_project["id"])

    def test_invitations_enforce_roles_and_keep_owner_connections_private(self):
        project = self.store.create_project(self.owner, project_values("SHARE-1"))
        project_connection = self.store.create_connection(self.owner, {
            "project_id": project["id"],
            "provider": "github",
            "label": "Shared repository",
            "account": "example/shared",
            "url": "https://github.com/example/shared",
        })
        owner_portfolio = self.store.portfolio(self.owner)
        self.assertEqual(len(owner_portfolio["connections"]), 5)

        first_invitation = self.store.create_share(
            self.owner,
            self.owner,
            project["id"],
            "Viewer@Example.com",
            "viewer",
        )
        rotated_invitation = self.store.create_share(
            self.owner,
            self.owner,
            project["id"],
            "viewer@example.com",
            "viewer",
        )
        self.assertEqual(first_invitation["share"]["id"], rotated_invitation["share"]["id"])
        self.assertNotEqual(first_invitation["token"], rotated_invitation["token"])

        with closing(sqlite3.connect(self.database_path)) as connection_db:
            raw_share = connection_db.execute(
                "SELECT invited_email, token_hash FROM project_shares WHERE id = ?",
                (rotated_invitation["share"]["id"],),
            ).fetchone()
        self.assertNotIn("viewer@example.com", raw_share[0])
        self.assertTrue(raw_share[0].startswith("gAAAA"))
        self.assertNotEqual(raw_share[1], rotated_invitation["token"])

        with self.assertRaisesRegex(KeyError, "another account"):
            self.store.invitation(rotated_invitation["token"], "wrong@example.com")
        with self.assertRaisesRegex(KeyError, "Invitation not found"):
            self.store.invitation(first_invitation["token"], "viewer@example.com")

        viewer_key = "viewer-user-id"
        self.store.accept_invitation(
            rotated_invitation["token"],
            viewer_key,
            "viewer@example.com",
        )
        viewer_portfolio = self.store.portfolio(viewer_key)
        shared_project = next(item for item in viewer_portfolio["projects"] if item["id"] == project["id"])
        self.assertEqual(shared_project["access_role"], "viewer")

        viewer_workspace = self.store.workspace(viewer_key, project["id"])
        self.assertFalse(viewer_workspace["permissions"]["can_edit"])
        self.assertEqual([item["id"] for item in viewer_workspace["connections"]], [project_connection["id"]])
        self.assertEqual(viewer_workspace["shares"], [])
        with self.assertRaisesRegex(PermissionError, "Editor access"):
            self.store.update_project(viewer_key, project["id"], {"progress": 50})
        with self.assertRaisesRegex(PermissionError, "Editor access"):
            self.store.create_record(viewer_key, project["id"], {
                "kind": "task",
                "title": "Viewer cannot add this",
                "details": "",
                "status": "open",
                "priority": "medium",
                "owner": "",
                "due_date": None,
                "resolution": "",
            })

        self.store.update_share(self.owner, rotated_invitation["share"]["id"], "editor")
        updated = self.store.update_project(viewer_key, project["id"], {"progress": 50})
        self.assertEqual(updated["progress"], 50)
        with self.assertRaisesRegex(PermissionError, "Owner access"):
            self.store.create_connection(viewer_key, {
                "project_id": project["id"],
                "provider": "github",
                "label": "Editor-controlled source",
                "account": "example/other",
                "url": "https://github.com/example/other",
            })
        with self.assertRaisesRegex(PermissionError, "Owner access"):
            self.store.update_connection(
                viewer_key, project_connection["id"], {"label": "Changed by editor"}
            )
        with self.assertRaisesRegex(PermissionError, "Owner access"):
            self.store.delete_connection(viewer_key, project_connection["id"])
        with self.assertRaisesRegex(PermissionError, "Owner access"):
            self.store.delete_project(viewer_key, project["id"])
        with self.assertRaisesRegex(PermissionError, "Owner access"):
            self.store.create_share(
                viewer_key,
                "viewer@example.com",
                project["id"],
                "third@example.com",
                "viewer",
            )

        self.store.delete_share(self.owner, rotated_invitation["share"]["id"])
        with self.assertRaisesRegex(KeyError, "Project not found"):
            self.store.workspace(viewer_key, project["id"])


class ProjectRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai_environment = patch.dict(os.environ, {
            "OPENAI_API_KEY": "test-key",
            "KASUGAI_AI_ALLOWED_USERS": "route@example.com",
            "KASUGAI_AI_SOURCE_ALLOWED_USERS": "route@example.com",
        })
        cls.ai_environment.start()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(cls.temporary_directory.name) / "routes.db"
        repository_root = Path(__file__).resolve().parents[1]
        cls.app = Flask(
            __name__,
            template_folder=str(repository_root / "sites" / "templates"),
            static_folder=str(repository_root / "sites" / "static"),
        )
        cls.app.secret_key = "project-test-secret"
        auth_test_bp = Blueprint("auth_bp", __name__)
        auth_test_bp.add_url_rule("/logout", "logout", lambda: "logged out")
        cls.app.register_blueprint(auth_test_bp)
        ui_test_bp = Blueprint("ui_bp", __name__)
        ui_test_bp.add_url_rule("/", "index", lambda: "home")
        ui_test_bp.add_url_rule("/screenshare", "screen_share", lambda: "screen share")
        cls.app.register_blueprint(ui_test_bp)
        init_project_routes(FakeConfig(database_path))
        cls.app.register_blueprint(project_bp)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()
        cls.ai_environment.stop()

    def setUp(self):
        with project_routes_module._ai_requests_lock:
            project_routes_module._ai_requests.clear()
        for owner_key in ("route-user", "editor-user", "tenant-b"):
            project_routes_module.store.delete_openai_api_key(owner_key)
        with self.client.session_transaction() as session:
            session["profile"] = {"id": "route-user", "email": "route@example.com"}

    def test_ai_preview_concurrency_limits_leave_web_workers_available(self):
        project = self.client.post(
            "/api/projects", json=project_values("AI-BUSY")
        ).get_json()

        with project_routes_module._ai_preview_lock:
            project_routes_module._ai_preview_users.add("route-user")
        try:
            same_user = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review this project"},
            )
        finally:
            with project_routes_module._ai_preview_lock:
                project_routes_module._ai_preview_users.discard("route-user")
        self.assertEqual(same_user.status_code, 429)
        self.assertIn("already running", same_user.get_json()["error"])

        with patch.object(
            project_routes_module._ai_preview_slots, "acquire", return_value=False
        ):
            globally_busy = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review this project"},
            )
        self.assertEqual(globally_busy.status_code, 503)
        self.assertEqual(globally_busy.headers["Retry-After"], "5")
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_project_api_crud_and_validation(self):
        values = project_values("api-1")
        response = self.client.post("/api/projects", json=values)
        self.assertEqual(response.status_code, 201)
        project = response.get_json()
        self.assertEqual(project["code"], "API-1")

        meeting_response = self.client.post(
            f"/api/projects/{project['id']}/meetings",
            json={"title": "Status review"},
        )
        self.assertEqual(meeting_response.status_code, 201)

        bad_url = self.client.post("/api/project-connections", json={
            "provider": "github",
            "label": "Unsafe link",
            "url": "https://user:password@example.com/repository",
            "project_id": project["id"],
        })
        self.assertEqual(bad_url.status_code, 400)
        self.assertIn("without embedded credentials", bad_url.get_json()["error"])

        portfolio = self.client.get("/api/projects/portfolio")
        self.assertEqual(portfolio.status_code, 200)
        self.assertEqual(portfolio.get_json()["summary"]["active_projects"], 1)

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "different-user"}
        hidden = self.client.get(f"/api/projects/{project['id']}")
        self.assertEqual(hidden.status_code, 404)

    def test_project_workspace_renders_with_security_headers(self):
        response = self.client.get("/projects")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ask Kasugai AI", response.data)
        self.assertIn(b"OpenAI API key settings", response.data)
        self.assertIn(b'<form id="openAISettingsForm" method="dialog"', response.data)
        self.assertIn(b'type="password"', response.data)
        self.assertIn(b'autocomplete="off"', response.data)
        self.assertIn(b"Apply selected changes", response.data)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")

        oversized = self.client.post(
            "/api/projects",
            data=b'{' + (b'"padding":"' + b'x' * (257 * 1024) + b'"}'),
            content_type="application/json",
        )
        self.assertEqual(oversized.status_code, 413)

    def test_personal_openai_key_settings_are_isolated_and_used_for_previews(self):
        first_key = "sk-route-user-personal-api-key"
        second_key = "sk-tenant-b-personal-api-key"
        deployment_key = "sk-deployment-api-key"
        proposal = {
            "summary": "Review", "answer": "No changes needed.", "actions": [],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": deployment_key,
            "KASUGAI_AI_ALLOWED_USERS": "route@example.com",
        }):
            cross_origin = self.client.put(
                "/api/project-ai/settings",
                json={"api_key": first_key},
                headers={"Origin": "https://attacker.example"},
            )
            self.assertEqual(cross_origin.status_code, 403)
            self.assertEqual(
                self.client.delete(
                    "/api/project-ai/settings",
                    headers={"Origin": "https://attacker.example"},
                ).status_code,
                403,
            )

            for invalid_key in ("", " leading", "line\nbreak", "x" * 4097):
                invalid = self.client.put(
                    "/api/project-ai/settings", json={"api_key": invalid_key}
                )
                self.assertEqual(invalid.status_code, 400)
                if invalid_key:
                    self.assertNotIn(invalid_key[:50], invalid.get_data(as_text=True))

            saved = self.client.put(
                "/api/project-ai/settings",
                json={"api_key": first_key},
                headers={"Origin": "http://localhost"},
            )
            self.assertEqual(saved.status_code, 200)
            first_settings = saved.get_json()
            self.assertTrue(first_settings["personal_key_configured"])
            self.assertEqual(first_settings["credential_source"], "personal")
            self.assertNotIn(first_key, saved.get_data(as_text=True))
            self.assertNotIn("api_key", first_settings)

            first_project = self.client.post(
                "/api/projects", json=project_values("AI-KEY-A")
            ).get_json()
            self.assertTrue(self.client.get(
                f"/api/projects/{first_project['id']}"
            ).get_json()["capabilities"]["ai_copilot"])
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.propose.return_value = proposal
                preview = self.client.post(
                    f"/api/projects/{first_project['id']}/assistant/preview",
                    json={"message": "Review using my key"},
                )
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(assistant_class.call_args.kwargs["api_key"], first_key)
            self.assertNotEqual(assistant_class.call_args.kwargs["api_key"], deployment_key)

            with self.client.session_transaction() as session:
                session["profile"] = {"id": "tenant-b", "email": "tenant-b@example.com"}
            tenant_settings = self.client.get("/api/project-ai/settings").get_json()
            self.assertFalse(tenant_settings["configured"])
            self.assertFalse(tenant_settings["personal_key_configured"])
            second_project = self.client.post(
                "/api/projects", json=project_values("AI-KEY-B")
            ).get_json()
            self.assertFalse(self.client.get(
                f"/api/projects/{second_project['id']}"
            ).get_json()["capabilities"]["ai_copilot"])

            second_saved = self.client.put(
                "/api/project-ai/settings", json={"api_key": second_key}
            )
            self.assertEqual(second_saved.get_json()["credential_source"], "personal")
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.propose.return_value = proposal
                preview = self.client.post(
                    f"/api/projects/{second_project['id']}/assistant/preview",
                    json={"message": "Review using tenant B's key"},
                )
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(assistant_class.call_args.kwargs["api_key"], second_key)

            removed_second = self.client.delete("/api/project-ai/settings")
            self.assertFalse(removed_second.get_json()["configured"])
            self.assertEqual(
                self.client.delete(f"/api/projects/{second_project['id']}").status_code,
                204,
            )

            with self.client.session_transaction() as session:
                session["profile"] = {"id": "route-user", "email": "route@example.com"}
            self.assertTrue(
                self.client.get("/api/project-ai/settings").get_json()["personal_key_configured"]
            )
            removed_first = self.client.delete("/api/project-ai/settings").get_json()
            self.assertFalse(removed_first["personal_key_configured"])
            self.assertEqual(removed_first["credential_source"], "deployment")
            self.assertEqual(
                self.client.delete(f"/api/projects/{first_project['id']}").status_code,
                204,
            )

    def test_corrupt_personal_key_fails_closed_until_removed(self):
        project = self.client.post(
            "/api/projects", json=project_values("AI-BROKEN-KEY")
        ).get_json()
        project_routes_module.store.set_openai_api_key(
            "route-user", "sk-personal-key-that-will-be-corrupted"
        )
        with closing(sqlite3.connect(project_routes_module.store.db_path)) as connection:
            connection.execute(
                """UPDATE project_user_credentials SET openai_api_key = ?
                   WHERE owner_key = ?""",
                ("not-a-fernet-token", "route-user"),
            )
            connection.commit()

        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-deployment-fallback-key",
            "KASUGAI_AI_ALLOWED_USERS": "route@example.com",
        }):
            settings = self.client.get("/api/project-ai/settings").get_json()
            self.assertTrue(settings["credential_error"])
            self.assertTrue(settings["deployment_key_available"])
            self.assertFalse(settings["configured"])
            self.assertIsNone(settings["credential_source"])
            workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
            self.assertFalse(workspace["capabilities"]["ai_copilot"])
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                preview = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Do not fall back to another account"},
                )
            self.assertEqual(preview.status_code, 502)
            assistant_class.assert_not_called()

            removed = self.client.delete("/api/project-ai/settings").get_json()
            self.assertFalse(removed["credential_error"])
            self.assertEqual(removed["credential_source"], "deployment")

        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_changes_require_a_signed_preview_and_confirmation(self):
        project = self.client.post("/api/projects", json=project_values("AI-1")).get_json()
        with patch("src.routes.project_routes.ProjectAssistant.propose") as invalid_propose:
            invalid_flag = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review", "include_github": "false"},
            )
        self.assertEqual(invalid_flag.status_code, 400)
        self.assertIn("must be true or false", invalid_flag.get_json()["error"])
        invalid_propose.assert_not_called()
        proposal = {
            "summary": "Delivery review",
            "answer": "One supported update is ready.",
            "actions": [{
                "type": "create_record",
                "reason": "A recent source identified a deployment risk.",
                "record_id": None,
                "fields": {
                    "kind": "risk", "title": "Deployment capacity",
                    "details": "Confirm production capacity before release.",
                    "status": "open", "priority": "high", "owner": "",
                    "due_date": None, "resolution": "",
                },
            }],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview_response = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review delivery risk"},
            )
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.get_json()

        tampered = dict(preview)
        tampered["proposal"] = dict(preview["proposal"])
        tampered["proposal"]["summary"] = "changed"
        with patch.dict(os.environ, {"KASUGAI_AI_ALLOWED_USERS": ""}):
            rejected = self.client.post(
                f"/api/projects/{project['id']}/assistant/apply", json=tampered
            )
        self.assertEqual(rejected.status_code, 400)

        with patch.dict(os.environ, {"KASUGAI_AI_ALLOWED_USERS": ""}):
            applied = self.client.post(
                f"/api/projects/{project['id']}/assistant/apply", json=preview
            )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.get_json()["applied"], 1)
        replayed = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=preview
        )
        self.assertEqual(replayed.status_code, 400)
        self.assertIn("already been applied", replayed.get_json()["error"])
        workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
        self.assertIn("Deployment capacity", {item["title"] for item in workspace["records"]})
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_is_atomic_when_a_project_invariant_fails(self):
        project = self.client.post("/api/projects", json=project_values("AI-ATOMIC")).get_json()
        proposal = {
            "summary": "Invalid combined change", "answer": "Preview",
            "actions": [
                {
                    "type": "create_record", "reason": "Test atomicity", "record_id": None,
                    "fields": {"kind": "task", "title": "Must roll back"},
                },
                {
                    "type": "update_project", "reason": "Invalid target", "record_id": None,
                    "fields": {"target_date": "2026-06-30"},
                },
            ],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Test atomic changes", "history": []},
            ).get_json()

        rejected = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=preview
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("target_date cannot be before start_date", rejected.get_json()["error"])
        workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
        self.assertNotIn("Must roll back", {item["title"] for item in workspace["records"]})
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_rejects_expired_and_stale_project_previews(self):
        project = self.client.post("/api/projects", json=project_values("AI-STALE-P")).get_json()
        proposal = {
            "summary": "Create a follow-up", "answer": "Preview",
            "actions": [{
                "type": "create_record", "reason": "Track the follow-up", "record_id": None,
                "fields": {"kind": "task", "title": "AI follow-up"},
            }],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            stale_preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Create a follow-up"},
            ).get_json()

        self.assertIn("expires_at", stale_preview["proposal"])
        self.assertEqual(
            stale_preview["proposal"]["expected_state"]["project_updated_at"],
            project["updated_at"],
        )
        self.assertEqual(
            self.client.patch(f"/api/projects/{project['id']}", json={"progress": 36}).status_code,
            200,
        )
        stale_response = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=stale_preview
        )
        self.assertEqual(stale_response.status_code, 400)
        self.assertIn("project changed", stale_response.get_json()["error"])

        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            expired_preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Create a follow-up"},
            ).get_json()
        expired_preview["proposal"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        expired_preview["signature"] = sign_proposal(
            self.app.secret_key, "route-user", project["id"], expired_preview["proposal"]
        )
        expired_response = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=expired_preview
        )
        self.assertEqual(expired_response.status_code, 400)
        self.assertIn("expired", expired_response.get_json()["error"])

        workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
        self.assertNotIn("AI follow-up", {item["title"] for item in workspace["records"]})
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_rejects_a_stale_target_record(self):
        project = self.client.post("/api/projects", json=project_values("AI-STALE-R")).get_json()
        record = self.client.post(
            f"/api/projects/{project['id']}/records",
            json={"kind": "task", "title": "Original task"},
        ).get_json()
        proposal = {
            "summary": "Complete a task", "answer": "Preview",
            "actions": [{
                "type": "update_record", "reason": "The work is complete",
                "record_id": record["id"], "fields": {"status": "done"},
            }],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Complete the task"},
            ).get_json()
        self.assertEqual(
            preview["proposal"]["expected_state"]["records_updated_at"][str(record["id"])],
            record["updated_at"],
        )

        self.assertEqual(
            self.client.patch(
                f"/api/project-records/{record['id']}", json={"title": "Human-edited task"}
            ).status_code,
            200,
        )
        rejected = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=preview
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("record changed", rejected.get_json()["error"])
        current = self.client.get(f"/api/projects/{project['id']}").get_json()["records"][0]
        self.assertEqual(current["title"], "Human-edited task")
        self.assertEqual(current["status"], "open")
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_rejects_unrelated_workspace_changes(self):
        project = self.client.post("/api/projects", json=project_values("AI-STALE-W")).get_json()
        proposal = {
            "summary": "Create a follow-up", "answer": "One follow-up is ready.",
            "actions": [{
                "type": "create_record", "reason": "Track the follow-up", "record_id": None,
                "fields": {"kind": "task", "title": "AI workspace follow-up"},
            }],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Create a follow-up"},
            ).get_json()

        self.assertEqual(self.client.post(
            f"/api/projects/{project['id']}/meetings",
            json={"title": "Human-added meeting", "held_on": "2026-07-14"},
        ).status_code, 201)
        rejected = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=preview
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("workspace changed", rejected.get_json()["error"])
        titles = {
            item["title"]
            for item in self.client.get(f"/api/projects/{project['id']}").get_json()["records"]
        }
        self.assertNotIn("AI workspace follow-up", titles)
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_can_select_individual_actions(self):
        project = self.client.post("/api/projects", json=project_values("AI-SELECT")).get_json()
        proposal = {
            "summary": "Two optional tasks", "answer": "Preview",
            "actions": [
                {
                    "type": "create_record", "reason": "First option", "record_id": None,
                    "fields": {"kind": "task", "title": "First optional task"},
                },
                {
                    "type": "create_record", "reason": "Second option", "record_id": None,
                    "fields": {"kind": "task", "title": "Second optional task"},
                },
            ],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Suggest two tasks"},
            ).get_json()

        duplicate_selection = dict(preview, selected_actions=[1, 1])
        rejected = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=duplicate_selection
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("duplicate", rejected.get_json()["error"])

        selected = dict(preview, selected_actions=[1])
        applied = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=selected
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.get_json()["applied"], 1)
        titles = {
            item["title"]
            for item in self.client.get(f"/api/projects/{project['id']}").get_json()["records"]
        }
        self.assertNotIn("First optional task", titles)
        self.assertIn("Second optional task", titles)
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_apply_rejects_conflicting_field_updates(self):
        project = self.client.post("/api/projects", json=project_values("AI-CONFLICT")).get_json()
        proposal = {
            "summary": "Conflicting progress updates", "answer": "Choose one value.",
            "actions": [
                {
                    "type": "update_project", "reason": "First estimate", "record_id": None,
                    "fields": {"progress": 40},
                },
                {
                    "type": "update_project", "reason": "Second estimate", "record_id": None,
                    "fields": {"progress": 60},
                },
            ],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch("src.routes.project_routes.ProjectAssistant.propose", return_value=proposal):
            preview = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Update progress"},
            ).get_json()

        rejected = self.client.post(
            f"/api/projects/{project['id']}/assistant/apply", json=preview
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("conflicting updates", rejected.get_json()["error"])
        self.assertEqual(
            self.client.get(f"/api/projects/{project['id']}").get_json()["project"]["progress"],
            35,
        )
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_shared_editor_ai_preview_cannot_use_owner_source_credentials(self):
        project = self.client.post("/api/projects", json=project_values("AI-EDITOR")).get_json()
        connection_response = self.client.post("/api/project-connections", json={
            "provider": "github",
            "label": "Owner repository",
            "account": "example/private",
            "url": "https://github.com/example/private",
            "project_id": project["id"],
        })
        self.assertEqual(connection_response.status_code, 201)
        invitation = self.client.post(
            f"/api/projects/{project['id']}/shares",
            json={"email": "editor@example.com", "role": "editor"},
        ).get_json()
        invitation_path = urlsplit(invitation["invitationUrl"]).path
        with self.client.session_transaction() as session:
            session["profile"] = {"id": "editor-user", "email": "editor@example.com"}
        self.assertEqual(self.client.post(invitation_path).status_code, 302)
        editor_key = "sk-shared-editor-personal-api-key"
        self.assertEqual(
            self.client.put(
                "/api/project-ai/settings", json={"api_key": editor_key}
            ).status_code,
            200,
        )

        proposal = {
            "summary": "No changes", "answer": "No changes are needed.", "actions": [],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch.dict(os.environ, {"KASUGAI_AI_ALLOWED_USERS": ""}), patch(
            "src.routes.project_routes.ProjectAssistant"
        ) as assistant_class:
            assistant_class.return_value.propose.return_value = proposal
            response = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review this project", "include_github": True, "include_email": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(assistant_class.call_args.kwargs["api_key"], editor_key)
        propose = assistant_class.return_value.propose
        self.assertEqual(propose.call_args.args[2], [])
        self.assertFalse(propose.call_args.kwargs["include_github"])
        self.assertFalse(propose.call_args.kwargs["include_email"])
        self.client.delete("/api/project-ai/settings")

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "route-user", "email": "route@example.com"}
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_ai_owner_needs_separate_source_allowlist(self):
        project = self.client.post("/api/projects", json=project_values("AI-SOURCE-GATE")).get_json()
        self.assertEqual(self.client.post("/api/project-connections", json={
            "provider": "github",
            "label": "Private repository",
            "account": "example/private",
            "url": "https://github.com/example/private",
            "project_id": project["id"],
        }).status_code, 201)
        proposal = {
            "summary": "No sources", "answer": "No external sources were used.", "actions": [],
            "evidence": [], "warnings": [], "model": "gpt-5.6-sol",
            "created_at": "2026-07-14T00:00:00Z",
        }
        with patch.dict(os.environ, {"KASUGAI_AI_SOURCE_ALLOWED_USERS": ""}), patch(
            "src.routes.project_routes.ProjectAssistant.propose", return_value=proposal
        ) as propose:
            workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
            response = self.client.post(
                f"/api/projects/{project['id']}/assistant/preview",
                json={"message": "Review private sources", "include_github": True},
            )
        self.assertFalse(workspace["capabilities"]["ai_sources"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(propose.call_args.args[2], [])
        self.assertFalse(propose.call_args.kwargs["include_github"])
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 204)

    def test_project_invitation_acceptance_role_change_and_revocation(self):
        project_response = self.client.post("/api/projects", json=project_values("API-SHARE"))
        self.assertEqual(project_response.status_code, 201)
        project = project_response.get_json()

        invitation_response = self.client.post(
            f"/api/projects/{project['id']}/shares",
            json={"email": "collaborator@example.com", "role": "viewer"},
        )
        self.assertEqual(invitation_response.status_code, 201)
        invitation = invitation_response.get_json()
        self.assertEqual(invitation["share"]["status"], "pending")
        invitation_path = urlsplit(invitation["invitationUrl"]).path

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "collaborator-user", "email": "collaborator@example.com"}
        invitation_page = self.client.get(invitation_path)
        self.assertEqual(invitation_page.status_code, 200)
        self.assertIn(b"Operations rollout", invitation_page.data)

        accepted = self.client.post(invitation_path)
        self.assertEqual(accepted.status_code, 302)
        self.assertTrue(accepted.headers["Location"].endswith(f"/projects?project={project['id']}"))

        shared_workspace = self.client.get(f"/api/projects/{project['id']}")
        self.assertEqual(shared_workspace.status_code, 200)
        self.assertEqual(shared_workspace.get_json()["permissions"]["role"], "viewer")
        viewer_edit = self.client.patch(
            f"/api/projects/{project['id']}",
            json={"progress": 60},
        )
        self.assertEqual(viewer_edit.status_code, 403)

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "route-user", "email": "route@example.com"}
        role_update = self.client.patch(
            f"/api/project-shares/{invitation['share']['id']}",
            json={"role": "editor"},
        )
        self.assertEqual(role_update.status_code, 200)

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "collaborator-user", "email": "collaborator@example.com"}
        editor_edit = self.client.patch(
            f"/api/projects/{project['id']}",
            json={"progress": 60},
        )
        self.assertEqual(editor_edit.status_code, 200)

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "route-user", "email": "route@example.com"}
        revoked = self.client.delete(f"/api/project-shares/{invitation['share']['id']}")
        self.assertEqual(revoked.status_code, 204)

        with self.client.session_transaction() as session:
            session["profile"] = {"id": "collaborator-user", "email": "collaborator@example.com"}
        removed_workspace = self.client.get(f"/api/projects/{project['id']}")
        self.assertEqual(removed_workspace.status_code, 404)


if __name__ == "__main__":
    unittest.main()
