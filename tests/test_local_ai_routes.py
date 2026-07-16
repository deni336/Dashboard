import http.client
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from flask import Flask

from src.project_ai import ProjectAIError
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


def project_values(code):
    return {
        "name": "Local AI integration",
        "code": code,
        "description": "Private project context",
        "status": "active",
        "priority": "high",
        "health": "on_track",
        "manager": "Project manager",
        "sponsor": "Project sponsor",
        "start_date": "2026-07-01",
        "target_date": "2026-09-30",
        "budget": 1000,
        "progress": 10,
    }


def proposal(answer="The local review is complete."):
    return {
        "summary": "Local review",
        "answer": answer,
        "actions": [],
        "evidence": [],
        "warnings": [],
        "model": "gpt-oss:20b",
        "created_at": "2026-07-15T00:00:00Z",
    }


def model_list_response(*model_ids):
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = json.dumps({
        "object": "list",
        "data": [{"id": model_id, "object": "model"} for model_id in model_ids],
    }).encode("utf-8")
    return response


class LocalAIRouteIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(
            os.environ,
            {
                "KASUGAI_AI_PROVIDER": "ollama",
                "KASUGAI_AI_BASE_URL": "http://ollama:11434/v1",
                "KASUGAI_AI_MODEL": "gpt-oss:20b",
                "KASUGAI_AI_API_KEY": "",
            },
        )
        cls.environment.start()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(cls.temporary_directory.name) / "local-ai-routes.db"
        cls.app = Flask(__name__)
        cls.app.secret_key = "local-ai-route-test-secret"
        init_project_routes(FakeConfig(database_path))
        cls.app.register_blueprint(project_bp)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temporary_directory.cleanup()
        cls.environment.stop()

    def setUp(self):
        with project_routes_module._ai_requests_lock:
            project_routes_module._ai_requests.clear()
        project_routes_module._clear_ai_readiness_cache()
        self.models_request = patch(
            "src.routes.project_routes.urllib.request.urlopen",
            return_value=model_list_response(
                "gpt-oss:20b",
                "gpt-oss:120b",
                "gpt-oss:20b-native",
            ),
        )
        self.models_request.start()
        self.addCleanup(self.models_request.stop)
        with self.client.session_transaction() as flask_session:
            flask_session["profile"] = {
                "id": "route-owner",
                "email": "owner@example.com",
            }

    def create_project(self, code):
        response = self.client.post("/api/projects", json=project_values(code))
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def delete_project(self, project_id):
        with self.client.session_transaction() as flask_session:
            flask_session["profile"] = {
                "id": "route-owner",
                "email": "owner@example.com",
            }
        self.assertEqual(
            self.client.delete(f"/api/projects/{project_id}").status_code,
            204,
        )

    def test_session_keeps_its_pinned_model_when_the_deployment_default_changes(self):
        project = self.create_project("AI-PIN")
        try:
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                first = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Start the local review"},
                )
            self.assertEqual(first.status_code, 200)
            session_id = first.get_json()["session"]["id"]

            with patch.dict(os.environ, {"KASUGAI_AI_MODEL": "gpt-oss:120b"}), patch(
                "src.routes.project_routes.ProjectAssistant"
            ) as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal(
                    "The pinned-model follow-up is complete."
                )
                second = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Continue", "session_id": session_id},
                )

            self.assertEqual(second.status_code, 200)
            self.assertEqual(assistant_class.call_args.args, ("gpt-oss:20b",))
            self.assertEqual(second.get_json()["session"]["model"], "gpt-oss:20b")
        finally:
            self.delete_project(project["id"])

    def test_ready_default_does_not_hide_a_missing_pinned_session_model(self):
        project = self.create_project("AI-PIN-MISSING")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner",
                project["id"],
                "Pinned model is unavailable",
                backend="ollama",
                model="gpt-oss:pinned-missing",
            )
            project_routes_module._clear_ai_readiness_cache()
            with patch(
                "src.routes.project_routes.urllib.request.urlopen",
                return_value=model_list_response("gpt-oss:20b"),
            ) as models_request:
                settings = self.client.get("/api/project-ai/settings").get_json()
                self.assertTrue(settings["ready"])

                with patch(
                    "src.routes.project_routes.ProjectAssistant"
                ) as assistant_class:
                    preview = self.client.post(
                        f"/api/projects/{project['id']}/assistant/preview",
                        json={
                            "message": "Use the pinned model",
                            "session_id": saved_session["id"],
                        },
                    )

            self.assertEqual(preview.status_code, 502)
            self.assertIn("'gpt-oss:pinned-missing' is not loaded", preview.get_json()["error"])
            assistant_class.assert_not_called()
            self.assertEqual(models_request.call_count, 2)
        finally:
            self.delete_project(project["id"])

    def test_ready_pinned_session_model_can_run_when_new_default_is_missing(self):
        project = self.create_project("AI-PIN-READY")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner",
                project["id"],
                "Pinned model remains available",
                backend="ollama",
                model="gpt-oss:pinned-ready",
            )
            project_routes_module._clear_ai_readiness_cache()
            with patch.dict(
                os.environ,
                {"KASUGAI_AI_MODEL": "gpt-oss:new-default-missing"},
            ), patch(
                "src.routes.project_routes.urllib.request.urlopen",
                return_value=model_list_response("gpt-oss:pinned-ready"),
            ) as models_request:
                settings = self.client.get("/api/project-ai/settings").get_json()
                self.assertFalse(settings["ready"])
                self.assertEqual(settings["readiness_status"], "model_missing")

                with patch(
                    "src.routes.project_routes.ProjectAssistant"
                ) as assistant_class:
                    assistant_class.return_value.model = "gpt-oss:pinned-ready"
                    assistant_class.return_value.propose.return_value = proposal(
                        "The pinned model completed the request."
                    )
                    preview = self.client.post(
                        f"/api/projects/{project['id']}/assistant/preview",
                        json={
                            "message": "Continue the existing conversation",
                            "session_id": saved_session["id"],
                        },
                    )

            self.assertEqual(preview.status_code, 200)
            self.assertEqual(
                assistant_class.call_args.args,
                ("gpt-oss:pinned-ready",),
            )
            self.assertEqual(
                preview.get_json()["session"]["model"],
                "gpt-oss:pinned-ready",
            )
            self.assertEqual(models_request.call_count, 2)
        finally:
            self.delete_project(project["id"])

    def test_shared_editors_have_separate_http_session_namespaces(self):
        project = self.create_project("AI-PRIVATE")
        try:
            invitation = project_routes_module.store.create_share(
                "route-owner",
                "owner@example.com",
                project["id"],
                "editor@example.com",
                "editor",
            )
            project_routes_module.store.accept_invitation(
                invitation["token"], "route-editor", "editor@example.com"
            )

            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                owner_result = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Owner-only conversation"},
                ).get_json()
            owner_session_id = owner_result["session"]["id"]

            with self.client.session_transaction() as flask_session:
                flask_session["profile"] = {
                    "id": "route-editor",
                    "email": "editor@example.com",
                }
            editor_list = self.client.get(
                f"/api/projects/{project['id']}/assistant/sessions"
            )
            self.assertEqual(editor_list.status_code, 200)
            self.assertEqual(editor_list.get_json()["sessions"], [])
            self.assertEqual(
                self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions/{owner_session_id}"
                ).status_code,
                404,
            )

            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                editor_result = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Editor-only conversation"},
                ).get_json()
            editor_session_id = editor_result["session"]["id"]

            with self.client.session_transaction() as flask_session:
                flask_session["profile"] = {
                    "id": "route-owner",
                    "email": "owner@example.com",
                }
            owner_sessions = self.client.get(
                f"/api/projects/{project['id']}/assistant/sessions"
            ).get_json()["sessions"]
            self.assertEqual([item["id"] for item in owner_sessions], [owner_session_id])
            self.assertNotIn(editor_session_id, [item["id"] for item in owner_sessions])
        finally:
            self.delete_project(project["id"])

    def test_failed_inference_or_turn_persistence_leaves_no_orphan_session(self):
        project = self.create_project("AI-ATOMIC")
        try:
            with patch(
                "src.project_manager.AI_SESSION_LIMIT_PER_PROJECT", 0
            ), patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                full = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Do not spend inference at capacity"},
                )
            self.assertEqual(full.status_code, 400)
            assistant_class.assert_not_called()

            with patch(
                "src.routes.project_routes.ProjectAssistant.propose",
                side_effect=ProjectAIError("The local model runner is unavailable"),
            ):
                inference_failure = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "This inference will fail"},
                )
            self.assertEqual(inference_failure.status_code, 502)
            self.assertEqual(
                self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions"
                ).get_json()["sessions"],
                [],
            )

            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class, patch.object(
                project_routes_module.store,
                "append_ai_turn",
                side_effect=ValueError("simulated turn persistence failure"),
            ):
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                persistence_failure = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "This persistence will fail"},
                )
            self.assertEqual(persistence_failure.status_code, 400)
            self.assertEqual(
                self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions"
                ).get_json()["sessions"],
                [],
            )
        finally:
            self.delete_project(project["id"])

    def test_session_rejects_a_backend_change_before_sending_context(self):
        project = self.create_project("AI-BACKEND")
        try:
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                first = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Start on local Ollama"},
                )
            self.assertEqual(first.status_code, 200)
            session_id = first.get_json()["session"]["id"]

            with patch.dict(
                os.environ,
                {
                    "KASUGAI_AI_PROVIDER": "openai",
                    "KASUGAI_AI_BASE_URL": "https://api.openai.com/v1",
                },
            ), patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                changed = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json={"message": "Do not cross providers", "session_id": session_id},
                )
            self.assertEqual(changed.status_code, 400)
            self.assertIn("different AI backend", changed.get_json()["error"])
            assistant_class.assert_not_called()
        finally:
            self.delete_project(project["id"])

    def test_disabled_or_invalid_provider_never_enables_the_copilot(self):
        project = self.create_project("AI-DISABLED")
        try:
            with patch.dict(
                os.environ,
                {"KASUGAI_AI_PROVIDER": "disabled", "KASUGAI_AI_BASE_URL": ""},
            ):
                settings = self.client.get("/api/project-ai/settings")
                self.assertEqual(settings.status_code, 200)
                self.assertFalse(settings.get_json()["configured"])
                workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
                self.assertFalse(workspace["capabilities"]["ai_copilot"])
                with patch(
                    "src.routes.project_routes.ProjectAssistant"
                ) as assistant_class:
                    preview = self.client.post(
                        f"/api/projects/{project['id']}/assistant/preview",
                        json={"message": "Must stay disabled"},
                    )
                self.assertEqual(preview.status_code, 403)
                assistant_class.assert_not_called()

            with patch.dict(os.environ, {"KASUGAI_AI_PROVIDER": "olama"}):
                invalid_settings = self.client.get("/api/project-ai/settings")
                self.assertEqual(invalid_settings.status_code, 502)
                workspace = self.client.get(f"/api/projects/{project['id']}").get_json()
                self.assertFalse(workspace["capabilities"]["ai_copilot"])
        finally:
            self.delete_project(project["id"])

    def test_session_route_pages_messages_older_than_the_latest_hundred(self):
        project = self.create_project("AI-PAGING")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner", project["id"], "Long route conversation"
            )
            for index in range(51):
                project_routes_module.store.append_ai_turn(
                    "route-owner",
                    project["id"],
                    saved_session["id"],
                    f"user-{index}",
                    f"assistant-{index}",
                    request_id=f"paging-{index}",
                )

            latest = self.client.get(
                f"/api/projects/{project['id']}/assistant/sessions/{saved_session['id']}"
            )
            self.assertEqual(latest.status_code, 200)
            latest_data = latest.get_json()
            self.assertEqual(len(latest_data["messages"]), 100)
            self.assertTrue(latest_data["has_more"])

            older = self.client.get(
                f"/api/projects/{project['id']}/assistant/sessions/{saved_session['id']}"
                f"?limit=100&before_id={latest_data['next_before_id']}"
            )
            self.assertEqual(older.status_code, 200)
            older_data = older.get_json()
            self.assertEqual(len(older_data["messages"]), 2)
            self.assertFalse(older_data["has_more"])
            self.assertEqual(older_data["messages"][0]["content"], "user-0")
        finally:
            self.delete_project(project["id"])

    def test_session_detail_reports_ready_pinned_model_without_probing_list(self):
        project = self.create_project("AI-DETAIL-READY")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner",
                project["id"],
                "Ready pinned model",
                backend="ollama",
                model="gpt-oss:pinned-ready",
            )
            project_routes_module._clear_ai_readiness_cache()
            with patch(
                "src.routes.project_routes.urllib.request.urlopen",
                return_value=model_list_response("gpt-oss:pinned-ready"),
            ) as models_request:
                session_list = self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions"
                )
                self.assertEqual(session_list.status_code, 200)
                models_request.assert_not_called()

                detail = self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions/{saved_session['id']}"
                ).get_json()

            readiness = detail["readiness"]
            self.assertTrue(readiness["configured"])
            self.assertTrue(readiness["ready"])
            self.assertEqual(readiness["readiness_status"], "ready")
            self.assertEqual(readiness["provider"], "ollama")
            self.assertEqual(readiness["provider_label"], "Local Ollama")
            self.assertEqual(readiness["model"], "gpt-oss:pinned-ready")
            self.assertEqual(readiness["current_provider"], "ollama")
            models_request.assert_called_once()
        finally:
            self.delete_project(project["id"])

    def test_session_detail_reports_missing_pinned_model(self):
        project = self.create_project("AI-DET-MISSING")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner",
                project["id"],
                "Missing pinned model",
                backend="ollama",
                model="gpt-oss:pinned-missing",
            )
            project_routes_module._clear_ai_readiness_cache()
            with patch(
                "src.routes.project_routes.urllib.request.urlopen",
                return_value=model_list_response("gpt-oss:20b"),
            ):
                detail = self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions/{saved_session['id']}"
                ).get_json()

            readiness = detail["readiness"]
            self.assertTrue(readiness["configured"])
            self.assertFalse(readiness["ready"])
            self.assertEqual(readiness["readiness_status"], "model_missing")
            self.assertIn("'gpt-oss:pinned-missing' is not loaded", readiness["message"])
        finally:
            self.delete_project(project["id"])

    def test_session_detail_backend_mismatch_does_not_probe(self):
        project = self.create_project("AI-DET-BACKEND")
        try:
            saved_session = project_routes_module.store.create_ai_session(
                "route-owner",
                project["id"],
                "Hosted backend session",
                backend="openai",
                model="gpt-hosted-session-model",
            )
            project_routes_module._clear_ai_readiness_cache()
            with patch(
                "src.routes.project_routes.urllib.request.urlopen"
            ) as models_request:
                detail = self.client.get(
                    f"/api/projects/{project['id']}/assistant/sessions/{saved_session['id']}"
                ).get_json()

            readiness = detail["readiness"]
            self.assertFalse(readiness["configured"])
            self.assertFalse(readiness["ready"])
            self.assertEqual(readiness["readiness_status"], "backend_mismatch")
            self.assertEqual(readiness["provider"], "openai")
            self.assertEqual(readiness["current_provider"], "ollama")
            self.assertIn("OpenAI API", readiness["message"])
            self.assertIn("Local Ollama", readiness["message"])
            models_request.assert_not_called()
        finally:
            self.delete_project(project["id"])

    def test_retry_with_client_ids_does_not_repeat_local_inference(self):
        project = self.create_project("AI-RETRY")
        try:
            request_id = str(uuid.uuid4())
            new_session_id = str(uuid.uuid4())
            request_body = {
                "message": "Store this turn once",
                "request_id": request_id,
                "new_session_id": new_session_id,
            }
            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                assistant_class.return_value.model = "gpt-oss:20b"
                assistant_class.return_value.propose.return_value = proposal()
                first = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json=request_body,
                )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.get_json()["session"]["id"], new_session_id)

            with patch("src.routes.project_routes.ProjectAssistant") as assistant_class:
                replay = self.client.post(
                    f"/api/projects/{project['id']}/assistant/preview",
                    json=request_body,
                )
            self.assertEqual(replay.status_code, 409)
            assistant_class.assert_not_called()
            saved = self.client.get(
                f"/api/projects/{project['id']}/assistant/sessions/{new_session_id}"
            ).get_json()
            self.assertEqual(len(saved["messages"]), 2)
        finally:
            self.delete_project(project["id"])

    def test_native_route_configuration_uses_ai_provider_base_url_and_model(self):
        ai_keys = [
            ("AI", "provider"),
            ("AI", "baseurl"),
            ("AI", "model"),
        ]
        previous = {
            key: project_routes_module.config.values.get(key) for key in ai_keys
        }
        project_routes_module.config.values.update({
            ("AI", "provider"): "ollama",
            ("AI", "baseurl"): "http://127.0.0.1:22434/v1",
            ("AI", "model"): "gpt-oss:20b-native",
        })
        try:
            with patch.dict(os.environ, {
                "KASUGAI_AI_PROVIDER": "",
                "KASUGAI_AI_BASE_URL": "",
                "KASUGAI_AI_MODEL": "",
            }):
                settings = self.client.get("/api/project-ai/settings")
                self.assertEqual(settings.status_code, 200)
                self.assertEqual(settings.get_json()["provider"], "ollama")
                self.assertEqual(settings.get_json()["model"], "gpt-oss:20b-native")
                self.assertEqual(
                    project_routes_module._assistant_base_url(),
                    "http://127.0.0.1:22434/v1",
                )
        finally:
            for key, value in previous.items():
                if value is None:
                    project_routes_module.config.values.pop(key, None)
                else:
                    project_routes_module.config.values[key] = value

    def test_unreachable_local_endpoint_is_configured_but_not_ready(self):
        project_routes_module._clear_ai_readiness_cache()
        with patch(
            "src.routes.project_routes.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ) as models_request:
            settings_response = self.client.get("/api/project-ai/settings")

            self.assertEqual(settings_response.status_code, 200)
            settings = settings_response.get_json()
            self.assertTrue(settings["configured"])
            self.assertFalse(settings["ready"])
            self.assertEqual(settings["readiness_status"], "unavailable")
            self.assertIn("Start the Ollama service", settings["message"])

            project = self.create_project("AI-OFFLINE")
            try:
                workspace = self.client.get(
                    f"/api/projects/{project['id']}"
                ).get_json()
                self.assertFalse(workspace["capabilities"]["ai_copilot"])
                with patch(
                    "src.routes.project_routes.ProjectAssistant"
                ) as assistant_class:
                    preview = self.client.post(
                        f"/api/projects/{project['id']}/assistant/preview",
                        json={"message": "Do not attempt inference"},
                    )
                self.assertEqual(preview.status_code, 502)
                self.assertIn("Start the Ollama service", preview.get_json()["error"])
                assistant_class.assert_not_called()
            finally:
                self.delete_project(project["id"])
        self.assertEqual(models_request.call_count, 1)

    def test_missing_exact_local_model_is_reported(self):
        project_routes_module._clear_ai_readiness_cache()
        with patch(
            "src.routes.project_routes.urllib.request.urlopen",
            return_value=model_list_response("gpt-oss:20b-latest", "other-model"),
        ):
            settings = self.client.get("/api/project-ai/settings").get_json()

        self.assertTrue(settings["configured"])
        self.assertFalse(settings["ready"])
        self.assertEqual(settings["readiness_status"], "model_missing")
        self.assertIn("'gpt-oss:20b' is not loaded", settings["message"])

    def test_incomplete_model_list_response_fails_closed(self):
        project_routes_module._clear_ai_readiness_cache()
        with patch(
            "src.routes.project_routes.urllib.request.urlopen",
            side_effect=http.client.IncompleteRead(b'{"data":', 100),
        ):
            response = self.client.get("/api/project-ai/settings")

        self.assertEqual(response.status_code, 200)
        settings = response.get_json()
        self.assertTrue(settings["configured"])
        self.assertFalse(settings["ready"])
        self.assertEqual(settings["readiness_status"], "unavailable")

    def test_unexpected_probe_failure_is_logged_without_request_details(self):
        project_routes_module._clear_ai_readiness_cache()
        with patch.object(
            project_routes_module,
            "_probe_local_ai_models",
            side_effect=RuntimeError("unexpected test transport failure"),
        ), patch.object(
            project_routes_module.logger,
            "warning",
        ) as warning:
            settings = self.client.get("/api/project-ai/settings").get_json()

        self.assertFalse(settings["ready"])
        self.assertEqual(settings["readiness_status"], "unavailable")
        warning.assert_called_once_with(
            "Unexpected local AI readiness probe failure.",
            exc_info=True,
        )

    def test_exact_local_model_marks_settings_and_workspace_ready(self):
        project_routes_module._clear_ai_readiness_cache()
        project = self.create_project("AI-READY")
        try:
            with patch(
                "src.routes.project_routes.urllib.request.urlopen",
                return_value=model_list_response("gpt-oss:20b"),
            ) as models_request:
                settings = self.client.get("/api/project-ai/settings").get_json()
                workspace = self.client.get(
                    f"/api/projects/{project['id']}"
                ).get_json()

            self.assertTrue(settings["configured"])
            self.assertTrue(settings["ready"])
            self.assertEqual(settings["readiness_status"], "ready")
            self.assertIsNone(settings["message"])
            self.assertTrue(workspace["capabilities"]["ai_copilot"])
            models_request.assert_called_once()
            request_call = models_request.call_args.args[0]
            self.assertEqual(
                request_call.full_url,
                "http://ollama:11434/v1/models",
            )
            self.assertEqual(
                models_request.call_args.kwargs["timeout"],
                project_routes_module.AI_READINESS_TIMEOUT_SECONDS,
            )
        finally:
            self.delete_project(project["id"])

    def test_local_readiness_probe_is_cached_and_keyed_by_model(self):
        project_routes_module._clear_ai_readiness_cache()
        with patch(
            "src.routes.project_routes.urllib.request.urlopen",
            return_value=model_list_response("gpt-oss:20b", "gpt-oss:120b"),
        ) as models_request:
            first = self.client.get("/api/project-ai/settings").get_json()
            second = self.client.get("/api/project-ai/settings").get_json()
            self.assertTrue(first["ready"])
            self.assertTrue(second["ready"])
            self.assertEqual(models_request.call_count, 1)

            with patch.dict(os.environ, {"KASUGAI_AI_MODEL": "gpt-oss:120b"}):
                changed_model = self.client.get(
                    "/api/project-ai/settings"
                ).get_json()
            self.assertTrue(changed_model["ready"])
            self.assertEqual(models_request.call_count, 2)

    def test_concurrent_cold_cache_uses_one_outbound_probe_per_model(self):
        project_routes_module._clear_ai_readiness_cache()
        worker_count = 8
        workers_ready = threading.Barrier(worker_count)
        probe_started = threading.Event()
        release_probe = threading.Event()

        def delayed_models_response(*_args, **_kwargs):
            probe_started.set()
            if not release_probe.wait(timeout=1):
                raise TimeoutError("test probe was not released")
            return model_list_response("gpt-oss:20b")

        def readiness_request():
            workers_ready.wait(timeout=1)
            return project_routes_module._local_ai_readiness()

        with patch(
            "src.routes.project_routes.urllib.request.urlopen",
            side_effect=delayed_models_response,
        ) as models_request, ThreadPoolExecutor(
            max_workers=worker_count
        ) as executor:
            futures = [
                executor.submit(readiness_request)
                for _index in range(worker_count)
            ]
            self.assertTrue(probe_started.wait(timeout=1))
            release_probe.set()
            results = [future.result(timeout=2) for future in futures]

        self.assertTrue(all(result["ready"] for result in results))
        self.assertEqual(models_request.call_count, 1)

    def test_hosted_openai_readiness_does_not_probe_model_catalogue(self):
        project_routes_module.store.set_openai_api_key(
            "route-owner", "sk-hosted-readiness-test"
        )
        try:
            project_routes_module._clear_ai_readiness_cache()
            with patch.dict(
                os.environ,
                {
                    "KASUGAI_AI_PROVIDER": "openai",
                    "KASUGAI_AI_BASE_URL": "https://api.openai.com/v1",
                },
            ), patch(
                "src.routes.project_routes.urllib.request.urlopen"
            ) as models_request:
                settings = self.client.get("/api/project-ai/settings").get_json()

            self.assertTrue(settings["configured"])
            self.assertTrue(settings["ready"])
            self.assertEqual(settings["readiness_status"], "ready")
            models_request.assert_not_called()
        finally:
            project_routes_module.store.delete_openai_api_key("route-owner")


if __name__ == "__main__":
    unittest.main()
