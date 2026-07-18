import io
import json
import os
import unittest
import urllib.error
from email.message import EmailMessage
from unittest.mock import patch

from src.project_ai import (
    IMAP_TIMEOUT_SECONDS,
    MAX_EMAIL_BODY_CHARS,
    MAX_EMAIL_FETCH_BYTES,
    MAX_EVIDENCE_ITEMS,
    MAX_SOURCE_CONNECTIONS,
    MAX_SOURCE_CHARS,
    ProjectAIError,
    ProjectAssistant,
)


class FakeIMAPClient:
    def __init__(self, raw_message):
        self.raw_message = raw_message
        self.login_args = None
        self.search_args = None
        self.fetch_args = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, username, password):
        self.login_args = (username, password)
        return "OK", []

    def select(self, mailbox, readonly=False):
        self.selected = (mailbox, readonly)
        return "OK", [b"1"]

    def search(self, *args):
        self.search_args = args
        return "OK", [b"1"]

    def fetch(self, *args):
        self.fetch_args = args
        return "OK", [(b"1 (BODY[] {123}", self.raw_message), b")"]


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit):
        return self.payload


class ProjectAssistantEmailTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "KASUGAI_IMAP_HOST": "imap.example.com",
            "KASUGAI_IMAP_PORT": "993",
            "KASUGAI_IMAP_USERNAME": "projects@example.com",
            "KASUGAI_IMAP_PASSWORD": "test-password",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.assistant = ProjectAssistant()

    def test_imap_uses_timeout_bounded_fetch_and_ignores_mime_attachments(self):
        message = EmailMessage()
        message["From"] = "Alice <alice@example.com>"
        message["To"] = "projects@example.com"
        message["Subject"] = "Delivery café update"
        message["Date"] = "Tue, 14 Jul 2026 12:00:00 +0000"
        message.set_content("Plain project status is green.")
        message.add_alternative(
            "<html><body><p>HTML alternative should not win.</p></body></html>",
            subtype="html",
        )
        message.add_attachment(
            "ATTACHMENT SECRET MUST NOT BE INGESTED",
            subtype="plain",
            filename="private.txt",
        )
        fake_client = FakeIMAPClient(message.as_bytes())

        with patch("src.project_ai.imaplib.IMAP4_SSL", return_value=fake_client) as constructor:
            evidence = self.assistant._email_evidence(
                {"id": 7, "provider": "gmail", "label": "Projects", "account": "projects@example.com"},
                {"code": "KAS-42", "name": "Delivery"},
            )

        self.assertEqual(constructor.call_args.args[:2], ("imap.example.com", 993))
        self.assertEqual(constructor.call_args.kwargs["timeout"], IMAP_TIMEOUT_SECONDS)
        self.assertEqual(fake_client.login_args, ("projects@example.com", "test-password"))
        self.assertEqual(
            fake_client.search_args,
            (None, '(OR SUBJECT "KAS-42" SUBJECT "Delivery")'),
        )
        self.assertEqual(
            fake_client.fetch_args,
            (b"1", f"(BODY.PEEK[]<0.{MAX_EMAIL_FETCH_BYTES}>)"),
        )
        item = evidence[0]["content"][0]
        self.assertEqual(item["subject"], "Delivery café update")
        self.assertIn("Plain project status is green.", item["body"])
        self.assertNotIn("HTML alternative", item["body"])
        self.assertNotIn("ATTACHMENT SECRET", item["body"])
        self.assertFalse(item["truncated"])

    def test_html_fallback_keeps_visible_text_and_drops_active_content(self):
        message = EmailMessage()
        message.set_content(
            """<html><head><style>.hidden { display:none }</style></head>
            <body><p>Visible update &amp; next step</p>
            <img style="display: none" src="tracking.gif"><p>Visible after tracking pixel</p>
            <div hidden>hidden attribute</div><div style="display: none">hidden style</div>
            <span aria-hidden="true">hidden aria</span>
            <script>stealSecrets()</script><svg><text>hidden diagram</text></svg></body></html>""",
            subtype="html",
        )

        parsed = self.assistant._extract_email_body(message)

        self.assertIn("Visible update & next step", parsed)
        self.assertIn("Visible after tracking pixel", parsed)
        self.assertNotIn("display:none", parsed)
        self.assertNotIn("stealSecrets", parsed)
        self.assertNotIn("hidden diagram", parsed)
        self.assertNotIn("hidden attribute", parsed)
        self.assertNotIn("hidden style", parsed)
        self.assertNotIn("hidden aria", parsed)

    def test_bounded_payload_never_copies_more_than_the_limit(self):
        raw, truncated = self.assistant._bounded_imap_payload(
            [(b"metadata", b"a" * (MAX_EMAIL_FETCH_BYTES + 100))],
            MAX_EMAIL_FETCH_BYTES,
        )

        self.assertEqual(len(raw), MAX_EMAIL_FETCH_BYTES)
        self.assertTrue(truncated)

    def test_email_body_is_capped_and_marked_truncated(self):
        message = EmailMessage()
        message["Subject"] = "Large update"
        message.set_content("x" * (MAX_EMAIL_BODY_CHARS + 500))
        fake_client = FakeIMAPClient(message.as_bytes())

        with patch("src.project_ai.imaplib.IMAP4_SSL", return_value=fake_client):
            evidence = self.assistant._email_evidence(
                {"account": "projects@example.com"}, {"code": "KAS-42"}
            )

        item = evidence[0]["content"][0]
        self.assertEqual(len(item["body"]), MAX_EMAIL_BODY_CHARS)
        self.assertTrue(item["truncated"])

    def test_invalid_imap_port_is_a_configuration_error(self):
        with patch.dict(os.environ, {"KASUGAI_IMAP_PORT": "not-a-port"}):
            with self.assertRaisesRegex(ProjectAIError, "valid TCP port"):
                self.assistant._email_evidence(
                    {"account": "projects@example.com"}, {"code": "KAS-42"}
                )

    def test_imap_connection_uses_only_the_remaining_source_budget(self):
        message = EmailMessage()
        message.set_content("Short update")
        fake_client = FakeIMAPClient(message.as_bytes())

        with patch("src.project_ai.time.monotonic", return_value=100.0), patch(
            "src.project_ai.imaplib.IMAP4_SSL", return_value=fake_client
        ) as constructor:
            self.assistant._email_evidence(
                {"account": "projects@example.com"},
                {"code": "KAS-42"},
                deadline=104.0,
            )

        self.assertEqual(constructor.call_args.kwargs["timeout"], 4.0)


class ProjectAssistantSourceLimitTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.assistant = ProjectAssistant()

    def test_propose_caps_connections_and_exposes_stable_evidence_ids(self):
        connections = [
            {"id": index, "provider": "github", "label": f"Repo {index}"}
            for index in range(1, MAX_SOURCE_CONNECTIONS + 3)
        ]
        captured = {}

        def github_evidence(connection, deadline=None):
            return [{
                "source": "github",
                "connection_id": connection["id"],
                "label": connection["label"],
                "kind": "issues",
                "url": f"https://github.com/example/repo-{connection['id']}",
                "content": [{"number": connection["id"], "title": "Open work"}],
            }]

        def openai_request(
            prompt, workspace, evidence, safety_identifier, history, deadline=None
        ):
            captured["evidence"] = evidence
            return {
                "summary": "Review",
                "answer": "One update is supported.",
                "actions": [{
                    "type": "update_project",
                    "reason": "Supported by the first repository.",
                    "evidence_refs": ["github-1"],
                    "record_id": None,
                    "fields": {"health": "at_risk"},
                }],
            }

        with patch.object(self.assistant, "_github_evidence", side_effect=github_evidence) as source_call:
            with patch.object(self.assistant, "_openai_request", side_effect=openai_request):
                result = self.assistant.propose(
                    "Review project health", {"project": {}}, connections
                )

        self.assertEqual(source_call.call_count, MAX_SOURCE_CONNECTIONS)
        self.assertEqual(
            [group["evidence_id"] for group in captured["evidence"]],
            [f"github-{index}" for index in range(1, MAX_SOURCE_CONNECTIONS + 1)],
        )
        self.assertEqual(
            [group["evidence_id"] for group in result["evidence"]],
            [f"github-{index}" for index in range(1, MAX_SOURCE_CONNECTIONS + 1)],
        )
        self.assertEqual(result["source_counts"]["connections_requested"], len(connections))
        self.assertEqual(result["source_counts"]["connections_processed"], MAX_SOURCE_CONNECTIONS)
        self.assertEqual(result["source_counts"]["connections_omitted"], 2)
        self.assertTrue(any("2 were omitted" in warning for warning in result["warnings"]))

    def test_evidence_items_have_a_global_limit_and_counts(self):
        evidence, counts = self.assistant._limit_evidence([{
            "source": "email",
            "label": "Projects",
            "content": [
                {"subject": f"Update {index}", "body": "Short status"}
                for index in range(MAX_EVIDENCE_ITEMS + 10)
            ],
        }])

        self.assertEqual(evidence[0]["evidence_id"], "email-1")
        self.assertEqual(len(evidence[0]["content"]), MAX_EVIDENCE_ITEMS)
        self.assertEqual(counts["items_discovered"], MAX_EVIDENCE_ITEMS + 10)
        self.assertEqual(counts["items_included"], MAX_EVIDENCE_ITEMS)

    def test_propose_reports_evidence_items_omitted_by_global_limit(self):
        source_items = [
            {"subject": f"Update {index}", "body": "Short status"}
            for index in range(MAX_EVIDENCE_ITEMS + 10)
        ]
        with patch.object(self.assistant, "_email_evidence", return_value=[{
            "source": "email", "label": "Projects", "content": source_items,
        }]):
            with patch.object(self.assistant, "_openai_request", return_value={
                "summary": "Review", "answer": "No changes proposed.", "actions": [],
            }):
                result = self.assistant.propose(
                    "Review email",
                    {"project": {}},
                    [{"provider": "gmail", "label": "Projects"}],
                    include_github=False,
                )

        self.assertEqual(result["source_counts"]["items_discovered"], MAX_EVIDENCE_ITEMS + 10)
        self.assertEqual(result["source_counts"]["items_included"], MAX_EVIDENCE_ITEMS)
        self.assertTrue(any(
            f"{MAX_EVIDENCE_ITEMS} of {MAX_EVIDENCE_ITEMS + 10} items" in warning
            for warning in result["warnings"]
        ))

    def test_actions_require_known_evidence_refs_but_allow_empty_refs(self):
        schemas = self.assistant._action_schemas()
        self.assertTrue(all("evidence_refs" in schema["required"] for schema in schemas))
        no_evidence_schemas = self.assistant._action_schemas([])
        self.assertTrue(all(
            schema["properties"]["evidence_refs"]["maxItems"] == 0
            for schema in no_evidence_schemas
        ))
        cited_schemas = self.assistant._action_schemas(["github-1", "email-1"])
        self.assertTrue(all(
            schema["properties"]["evidence_refs"]["items"]["enum"]
            == ["github-1", "email-1"]
            for schema in cited_schemas
        ))

        with patch.object(self.assistant, "_github_evidence", return_value=[]):
            with patch.object(self.assistant, "_openai_request", return_value={
                "summary": "Requested change",
                "answer": "Ready for review.",
                "actions": [{
                    "type": "update_project", "reason": "The user explicitly requested it.",
                    "evidence_refs": [], "record_id": None, "fields": {"progress": 50},
                }],
            }):
                result = self.assistant.propose(
                    "Set progress to 50", {"project": {}}, [], include_github=False
                )
        self.assertEqual(result["actions"][0]["evidence_refs"], [])

        with patch.object(self.assistant, "_github_evidence", return_value=[]):
            with patch.object(self.assistant, "_openai_request", return_value={
                "summary": "Bad reference",
                "answer": "Invalid.",
                "actions": [{
                    "type": "update_project", "reason": "Unsupported source.",
                    "evidence_refs": ["github-999"], "record_id": None,
                    "fields": {"progress": 50},
                }],
            }):
                with self.assertRaisesRegex(ProjectAIError, "unsupported project action"):
                    self.assistant.propose("Update", {"project": {}}, [])

    def test_context_compaction_preserves_the_bounded_evidence_set(self):
        evidence, _counts = self.assistant._limit_evidence([{
            "source": "email",
            "label": "Projects",
            "content": [
                {"subject": f"Update {index}", "body": "Evidence " + ("e" * 500)}
                for index in range(30)
            ],
        }])
        workspace = {
            "project": {"name": "Large project", "description": "p" * 10_000},
            "permissions": {"can_edit": True},
            "records": [
                {"id": index, "title": f"Task {index}", "details": "x" * 5_000}
                for index in range(40)
            ],
            "meetings": [],
            "stakeholders": [],
        }

        serialized = self.assistant._prepare_openai_input(
            "Review all evidence", workspace, evidence, []
        )
        sent = json.loads(serialized)

        self.assertLessEqual(len(serialized), MAX_SOURCE_CHARS)
        self.assertEqual(
            len(sent["evidence"][0]["content"]), len(evidence[0]["content"])
        )
        self.assertLess(len(sent["workspace"]["records"]), len(workspace["records"]))
        self.assertIn("compacted", self.assistant._last_context_warning)


class ProjectAssistantCompatibleEndpointTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "KASUGAI_AI_BASE_URL": "http://ollama:11434/v1/",
            "KASUGAI_AI_MODEL": "gpt-oss:20b",
            "KASUGAI_AI_API_KEY": "",
            "KASUGAI_AI_TIMEOUT_SECONDS": "",
            "KASUGAI_AI_REQUEST_BUDGET_SECONDS": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.assistant = ProjectAssistant(api_key="")

    def test_chat_completion_parses_structured_output(self):
        result = self.assistant._parse_openai_response(json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"summary":"Ready","answer":"Done","actions":[]}',
                },
            }],
        }).encode())

        self.assertEqual(result["summary"], "Ready")

    def test_chat_request_uses_configured_endpoint_model_and_strict_schema(self):
        response = FakeHTTPResponse(json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": '{"summary":"Ready","answer":"Done","actions":[]}',
                },
            }],
        }).encode())

        with patch("src.project_ai.urllib.request.urlopen", return_value=response) as request:
            result = self.assistant._openai_request(
                "Review the project",
                {"project": {"name": "Delivery"}, "records": []},
                [],
                "a" * 64,
                [],
            )

        upstream_request = request.call_args.args[0]
        sent = json.loads(upstream_request.data)
        self.assertEqual(upstream_request.full_url, "http://ollama:11434/v1/chat/completions")
        self.assertIsNone(upstream_request.get_header("Authorization"))
        self.assertEqual(sent["model"], "gpt-oss:20b")
        self.assertEqual([item["role"] for item in sent["messages"]], ["system", "user"])
        self.assertIn("untrusted data", sent["messages"][0]["content"])
        user_input = json.loads(sent["messages"][1]["content"])
        self.assertEqual(user_input["request"], "Review the project")
        self.assertFalse(sent["stream"])
        self.assertEqual(sent["temperature"], 0)
        self.assertEqual(sent["reasoning_effort"], "medium")
        self.assertEqual(sent["user"], "a" * 64)
        self.assertTrue(sent["response_format"]["json_schema"]["strict"])
        self.assertFalse(
            sent["response_format"]["json_schema"]["schema"]["additionalProperties"]
        )
        self.assertEqual(result["summary"], "Ready")

    def test_no_api_key_is_required_and_service_credentials_are_optional(self):
        self.assertTrue(self.assistant.configured)
        self.assertEqual(self.assistant.api_key, "")
        with patch.dict(os.environ, {"KASUGAI_AI_BASE_URL": ""}):
            default_endpoint = ProjectAssistant(api_key="")
        self.assertEqual(default_endpoint.base_url, "http://ollama:11434/v1")

        response = FakeHTTPResponse(b'{}')
        protected = ProjectAssistant(api_key="service-secret")
        with patch("src.project_ai.urllib.request.urlopen", return_value=response) as request:
            protected._openai_post(b"{}")
        self.assertEqual(
            request.call_args.args[0].get_header("Authorization"),
            "Bearer service-secret",
        )

    def test_explicit_model_is_pinned_and_environment_supplies_the_default(self):
        with patch.dict(os.environ, {"KASUGAI_AI_MODEL": ""}):
            self.assertEqual(ProjectAssistant("custom-local", api_key="").model, "custom-local")
        with patch.dict(os.environ, {"KASUGAI_AI_MODEL": "environment-local"}):
            self.assertEqual(ProjectAssistant("argument-local", api_key="").model, "argument-local")
            self.assertEqual(ProjectAssistant(api_key="").model, "environment-local")

    def test_base_url_is_normalized_and_unsafe_values_are_rejected(self):
        assistant = ProjectAssistant(api_key="", base_url="https://models.example/v1/")
        self.assertEqual(assistant.base_url, "https://models.example/v1")
        self.assertEqual(
            assistant.chat_completions_url,
            "https://models.example/v1/chat/completions",
        )

        for value in (
            "",
            "ftp://models.example/v1",
            "http://user:password@models.example/v1",
            "http://models.example/v1?tenant=a",
            "http://models.example/v1#fragment",
            "http://models.example:invalid/v1",
            "http://models.example/v1 with-space",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ProjectAIError, "KASUGAI_AI_BASE_URL"):
                    ProjectAssistant(api_key="", base_url=value)

    def test_local_inference_budget_is_configurable_and_bounded(self):
        with patch.dict(os.environ, {
            "KASUGAI_AI_TIMEOUT_SECONDS": "345",
            "KASUGAI_AI_REQUEST_BUDGET_SECONDS": "400",
        }):
            assistant = ProjectAssistant(api_key="")
        self.assertEqual(assistant.timeout_seconds, 345.0)
        self.assertEqual(assistant.request_budget_seconds, 400.0)

        for name, value in (
            ("KASUGAI_AI_TIMEOUT_SECONDS", "4"),
            ("KASUGAI_AI_TIMEOUT_SECONDS", "not-a-number"),
            ("KASUGAI_AI_TIMEOUT_SECONDS", "nan"),
            ("KASUGAI_AI_REQUEST_BUDGET_SECONDS", "1201"),
        ):
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}):
                with self.assertRaisesRegex(ProjectAIError, name):
                    ProjectAssistant(api_key="")

    def test_incomplete_and_refused_completions_are_clear_errors(self):
        with self.assertRaisesRegex(ProjectAIError, "token limit"):
            self.assistant._parse_openai_response(json.dumps({
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            }).encode())
        with self.assertRaisesRegex(ProjectAIError, "declined"):
            self.assistant._parse_openai_response(json.dumps({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "", "refusal": "Cannot comply"},
                }],
            }).encode())

        for payload in ({}, {"choices": []}, {"choices": [{"message": {"content": "[]"}}]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ProjectAIError):
                    self.assistant._parse_openai_response(json.dumps(payload).encode())

    def test_transient_endpoint_error_is_retried_once(self):
        error = urllib.error.HTTPError(
            "http://ollama:11434/v1/chat/completions",
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            io.BytesIO(b'{"error":{"message":"Slow down"}}'),
        )
        success = FakeHTTPResponse(b'{"choices":[]}')

        with patch("src.project_ai.urllib.request.urlopen", side_effect=[error, success]) as request:
            with patch("src.project_ai.time.sleep") as sleep:
                raw = self.assistant._openai_post(b"{}")

        self.assertEqual(raw, success.payload)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_http_error_exposes_only_structured_error_message(self):
        error = urllib.error.HTTPError(
            "http://ollama:11434/v1/chat/completions",
            400,
            "Bad Request",
            {},
            io.BytesIO(b"<html>upstream details</html>"),
        )

        with patch("src.project_ai.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ProjectAIError, r"AI endpoint request failed \(400\)$"):
                self.assistant._openai_post(b"{}")

    def test_endpoint_errors_never_echo_configured_credentials(self):
        service_key = "sk-proj-privatevalueabcd"
        assistant = ProjectAssistant(api_key=service_key)
        error = urllib.error.HTTPError(
            "http://ollama:11434/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                f'{{"error":{{"message":"Bad {service_key}; shown as sk-proj-****abcd"}}}}'.encode()
            ),
        )

        with patch("src.project_ai.urllib.request.urlopen", side_effect=error) as request:
            with self.assertRaises(ProjectAIError) as raised:
                assistant._openai_post(b"{}")

        message = str(raised.exception)
        self.assertNotIn(service_key, message)
        self.assertNotIn("abcd", message)
        self.assertIn("Check the configured AI API credential", message)
        self.assertEqual(
            request.call_args.args[0].get_header("Authorization"),
            f"Bearer {service_key}",
        )

    def test_github_deployment_token_requires_a_repository_target(self):
        with patch.dict(
            os.environ,
            {"KASUGAI_GITHUB_TOKEN_ALLOWLIST": "example/*"},
            clear=False,
        ):
            self.assertFalse(self.assistant._github_token_allowed(["example"]))
            self.assertTrue(
                self.assistant._github_token_allowed(["example", "project"])
            )

    def test_upstream_calls_use_and_enforce_the_remaining_request_budget(self):
        github_response = FakeHTTPResponse(b"[]")
        openai_response = FakeHTTPResponse(b'{}')
        with patch("src.project_ai.time.monotonic", return_value=100.0), patch(
            "src.project_ai.urllib.request.urlopen",
            side_effect=[github_response, openai_response],
        ) as request:
            self.assertEqual(
                self.assistant._json_get(
                    "https://api.github.com/repos/example/repo/issues",
                    {},
                    deadline=103.0,
                ),
                [],
            )
            self.assertEqual(self.assistant._openai_post(b"{}", deadline=102.0), b"{}")

        self.assertEqual(request.call_args_list[0].kwargs["timeout"], 3.0)
        self.assertEqual(request.call_args_list[1].kwargs["timeout"], 2.0)

        with patch("src.project_ai.time.monotonic", return_value=101.0), patch(
            "src.project_ai.urllib.request.urlopen"
        ) as request:
            with self.assertRaisesRegex(ProjectAIError, "request time budget"):
                self.assistant._openai_post(b"{}", deadline=100.0)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
