import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from cryptography.fernet import Fernet
from flask import Flask

from src.project_manager import ProjectStore
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


class ProjectRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(cls.temporary_directory.name) / "routes.db"
        cls.app = Flask(__name__)
        cls.app.secret_key = "project-test-secret"
        init_project_routes(FakeConfig(database_path))
        cls.app.register_blueprint(project_bp)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()

    def setUp(self):
        with self.client.session_transaction() as session:
            session["profile"] = {"id": "route-user", "email": "route@example.com"}

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


if __name__ == "__main__":
    unittest.main()
