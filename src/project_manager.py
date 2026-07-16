import hashlib
import json
import hmac
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from src.config_handler import get_default_config_path
from src.global_logger import GlobalLogger


DEFAULT_CONNECTIONS = (
    ("github", "GitHub", "", "https://github.com/"),
    ("gmail", "Gmail", "", "https://mail.google.com/"),
    ("calendar", "Google Calendar", "", "https://calendar.google.com/"),
    ("drive", "Google Drive", "", "https://drive.google.com/"),
    ("teams", "Microsoft Teams", "", "https://teams.microsoft.com/"),
)

ENCRYPTED_FIELDS = {
    "projects": {"description"},
    "project_records": {"details", "resolution"},
    "project_meetings": {"attendees", "notes", "decisions", "action_items", "next_steps"},
    "project_stakeholders": {"notes"},
    "project_connections": {"account"},
    "project_shares": {"invited_email", "invited_by_email"},
    "project_ai_sessions": {"title"},
    "project_ai_messages": {"content", "model_context"},
}

PRIVATE_API_FIELDS = {
    "projects": {"owner_key"},
    "project_records": {"owner_key"},
    "project_meetings": {"owner_key"},
    "project_stakeholders": {"owner_key"},
    "project_connections": {"owner_key"},
    "project_shares": {
        "owner_key",
        "member_owner_key",
        "invited_email_hash",
        "token_hash",
    },
    "project_ai_audit": {"summary", "actions"},
    "project_ai_sessions": {"actor_key"},
    "project_ai_messages": {"actor_key", "project_id", "model_context", "request_id"},
}

CHILD_TABLES = {
    "project_records",
    "project_meetings",
    "project_stakeholders",
    "project_connections",
}

ACCESS_LEVELS = {"viewer": 0, "editor": 1, "owner": 2}
INVITATION_LIFETIME = timedelta(days=7)
AI_SESSION_LIMIT_PER_PROJECT = 50
AI_SESSION_MESSAGE_LIMIT = 500
AI_SESSION_TITLE_MAX_LENGTH = 160
AI_SESSION_BACKEND_MAX_LENGTH = 40
AI_SESSION_MODEL_MAX_LENGTH = 100
AI_SESSION_MESSAGE_MAX_LENGTH = 5000
AI_SESSION_CONTEXT_MAX_LENGTH = 5000
AI_SESSION_PAGE_MAX_LENGTH = 200


class ProjectStore:
    """Collaborative project portfolio stored in SQLite with encrypted private text."""

    def __init__(self, config):
        self.logger = GlobalLogger.get_logger("ProjectStore")
        key = config.get("Database", "encryption_key")
        if not key:
            key = Fernet.generate_key().decode("ascii")
            config.set("Database", "encryption_key", key)
        self.fernet = Fernet(key.encode("ascii"))
        self.lookup_key = hashlib.sha256(b"Kasugai/project-sharing/v1\x00" + key.encode("ascii")).digest()

        configured_path = config.get("Database", "projectdbpath", fallback="project_manager.db")
        if os.path.isabs(configured_path):
            self.db_path = configured_path
        else:
            self.db_path = os.path.join(os.path.dirname(get_default_config_path()), configured_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned'
                        CHECK (status IN ('planned', 'active', 'on_hold', 'completed', 'archived')),
                    priority TEXT NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
                    health TEXT NOT NULL DEFAULT 'on_track'
                        CHECK (health IN ('on_track', 'at_risk', 'off_track')),
                    manager TEXT NOT NULL DEFAULT '',
                    sponsor TEXT NOT NULL DEFAULT '',
                    start_date TEXT,
                    target_date TEXT,
                    budget REAL NOT NULL DEFAULT 0 CHECK (budget >= 0),
                    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_key, code)
                );

                CREATE TABLE IF NOT EXISTS project_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL
                        CHECK (kind IN ('task', 'milestone', 'risk', 'assumption', 'issue', 'dependency', 'decision')),
                    title TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'blocked', 'monitoring', 'resolved', 'done')),
                    priority TEXT NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
                    owner TEXT NOT NULL DEFAULT '',
                    due_date TEXT,
                    resolution TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_records_project_idx
                    ON project_records(owner_key, project_id, kind, status, due_date);

                CREATE TABLE IF NOT EXISTS project_meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    held_on TEXT NOT NULL,
                    attendees TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    decisions TEXT NOT NULL DEFAULT '',
                    action_items TEXT NOT NULL DEFAULT '',
                    next_steps TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_meetings_project_idx
                    ON project_meetings(owner_key, project_id, held_on DESC);

                CREATE TABLE IF NOT EXISTS project_stakeholders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    influence TEXT NOT NULL DEFAULT 'medium'
                        CHECK (influence IN ('low', 'medium', 'high')),
                    engagement TEXT NOT NULL DEFAULT 'neutral'
                        CHECK (engagement IN ('unaware', 'resistant', 'neutral', 'supportive', 'leading')),
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_stakeholders_project_idx
                    ON project_stakeholders(owner_key, project_id, influence);

                CREATE TABLE IF NOT EXISTS project_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_key TEXT NOT NULL,
                    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    label TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS project_connections_owner_idx
                    ON project_connections(owner_key, project_id, provider);

                CREATE TABLE IF NOT EXISTS project_user_state (
                    owner_key TEXT PRIMARY KEY,
                    defaults_seeded INTEGER NOT NULL DEFAULT 0 CHECK (defaults_seeded IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS project_user_credentials (
                    owner_key TEXT PRIMARY KEY,
                    openai_api_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_key TEXT NOT NULL,
                    invited_email_hash TEXT NOT NULL,
                    invited_email TEXT NOT NULL,
                    invited_by_email TEXT NOT NULL,
                    member_owner_key TEXT,
                    role TEXT NOT NULL CHECK (role IN ('viewer', 'editor')),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'accepted')),
                    token_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    accepted_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, invited_email_hash)
                );
                CREATE INDEX IF NOT EXISTS project_shares_member_idx
                    ON project_shares(member_owner_key, status, project_id);
                CREATE INDEX IF NOT EXISTS project_shares_invitation_idx
                    ON project_shares(token_hash, invited_email_hash, status);

                CREATE TABLE IF NOT EXISTS project_ai_sessions (
                    id TEXT PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    actor_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(id, project_id, actor_key)
                );
                CREATE INDEX IF NOT EXISTS project_ai_sessions_actor_idx
                    ON project_ai_sessions(actor_key, project_id, updated_at DESC, id);

                CREATE TABLE IF NOT EXISTS project_ai_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    project_id INTEGER NOT NULL,
                    actor_key TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    request_id TEXT,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    model_context TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id, project_id, actor_key)
                        REFERENCES project_ai_sessions(id, project_id, actor_key)
                        ON DELETE CASCADE,
                    UNIQUE(session_id, turn_id, role),
                    UNIQUE(session_id, request_id, role)
                );
                CREATE INDEX IF NOT EXISTS project_ai_messages_session_idx
                    ON project_ai_messages(session_id, id);

                CREATE TABLE IF NOT EXISTS project_ai_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    owner_key TEXT NOT NULL,
                    actor_key TEXT NOT NULL,
                    model TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    actions TEXT NOT NULL,
                    applied_count INTEGER NOT NULL,
                    proposal_signature TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            audit_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(project_ai_audit)")
            }
            if "proposal_signature" not in audit_columns:
                connection.execute("ALTER TABLE project_ai_audit ADD COLUMN proposal_signature TEXT")
            connection.execute(
                """CREATE INDEX IF NOT EXISTS project_ai_audit_project_idx
                   ON project_ai_audit(owner_key, project_id, created_at DESC)"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS project_ai_audit_signature_idx
                   ON project_ai_audit(proposal_signature)
                   WHERE proposal_signature IS NOT NULL"""
            )
        self.logger.info(f"Connected to project database at {self.db_path}")

    @staticmethod
    def _now():
        return datetime.now(UTC).isoformat()

    def _encrypt(self, value):
        return self.fernet.encrypt((value or "").encode("utf-8")).decode("ascii")

    def _decrypt(self, value):
        if not value:
            return ""
        try:
            return self.fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError):
            return value

    def _decrypt_secret(self, value):
        """Decrypt a credential without the legacy plaintext fallback used by project fields."""
        try:
            return self.fernet.decrypt(str(value).encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise ValueError("The stored credential could not be decrypted") from exc

    def _row(self, table, row):
        if row is None:
            return None
        result = dict(row)
        for field in ENCRYPTED_FIELDS.get(table, set()):
            if field in result:
                result[field] = self._decrypt(result[field])
        for field in PRIVATE_API_FIELDS.get(table, set()):
            result.pop(field, None)
        return result

    def _rows(self, table, rows):
        return [self._row(table, row) for row in rows]

    @staticmethod
    def _normalize_email(email):
        return str(email or "").strip().lower()

    def _email_hash(self, email):
        return hmac.new(
            self.lookup_key,
            self._normalize_email(email).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _token_hash(token):
        return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()

    def _access_project(self, connection, actor_key, project_id, required="viewer"):
        row = connection.execute(
            """
            SELECT p.id, p.owner_key,
                   CASE WHEN p.owner_key = ? THEN 'owner' ELSE (
                       SELECT s.role FROM project_shares s
                       WHERE s.project_id = p.id AND s.member_owner_key = ?
                         AND s.status = 'accepted' LIMIT 1
                   ) END AS access_role
            FROM projects p
            WHERE p.id = ? AND (
                p.owner_key = ? OR EXISTS (
                    SELECT 1 FROM project_shares s
                    WHERE s.project_id = p.id AND s.member_owner_key = ?
                      AND s.status = 'accepted'
                )
            )
            """,
            (actor_key, actor_key, project_id, actor_key, actor_key),
        ).fetchone()
        if row is None:
            raise KeyError("Project not found")
        if ACCESS_LEVELS[row["access_role"]] < ACCESS_LEVELS[required]:
            raise PermissionError(f"{required.title()} access is required")
        return row

    def _owned_project(self, connection, actor_key, project_id):
        return self._access_project(connection, actor_key, project_id, required="owner")

    def ensure_default_connections(self, owner_key):
        with self._connect() as connection:
            state = connection.execute(
                "SELECT defaults_seeded FROM project_user_state WHERE owner_key = ?",
                (owner_key,),
            ).fetchone()
            if state is not None and state["defaults_seeded"]:
                return
            now = self._now()
            connection.executemany(
                """
                INSERT INTO project_connections
                    (owner_key, project_id, provider, label, account, url, created_at, updated_at)
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (owner_key, provider, label, self._encrypt(account), url, now, now)
                    for provider, label, account, url in DEFAULT_CONNECTIONS
                ],
            )
            connection.execute(
                """
                INSERT INTO project_user_state (owner_key, defaults_seeded) VALUES (?, 1)
                ON CONFLICT(owner_key) DO UPDATE SET defaults_seeded = 1
                """,
                (owner_key,),
            )

    def openai_api_key(self, owner_key):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT openai_api_key FROM project_user_credentials WHERE owner_key = ?",
                (owner_key,),
            ).fetchone()
        return self._decrypt_secret(row["openai_api_key"]) if row else ""

    def openai_credential_status(self, owner_key):
        with self._connect() as connection:
            row = connection.execute(
                """SELECT openai_api_key, updated_at FROM project_user_credentials
                   WHERE owner_key = ?""",
                (owner_key,),
            ).fetchone()
        if not row:
            return {
                "personal_key_configured": False,
                "updated_at": None,
            }
        self._decrypt_secret(row["openai_api_key"])
        return {
            "personal_key_configured": True,
            "updated_at": row["updated_at"],
        }

    def set_openai_api_key(self, owner_key, api_key):
        now = self._now()
        encrypted_key = self._encrypt(api_key)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_user_credentials
                    (owner_key, openai_api_key, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(owner_key) DO UPDATE SET
                    openai_api_key = excluded.openai_api_key,
                    updated_at = excluded.updated_at
                """,
                (owner_key, encrypted_key, now, now),
            )
        return self.openai_credential_status(owner_key)

    def delete_openai_api_key(self, owner_key):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM project_user_credentials WHERE owner_key = ?",
                (owner_key,),
            )

    @staticmethod
    def _ai_session_value(value, field, maximum, *, required=True, default=""):
        if value is None:
            value = default
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        value = value.strip()
        if required and not value:
            raise ValueError(f"{field} is required")
        if len(value) > maximum:
            raise ValueError(f"{field} must be {maximum} characters or fewer")
        return value

    @staticmethod
    def _ai_session_page_value(value, field, maximum):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        if not 1 <= value <= maximum:
            raise ValueError(f"{field} must be between 1 and {maximum}")
        return value

    def _access_ai_session(
        self, connection, actor_key, project_id, session_id, *, required="viewer"
    ):
        self._access_project(connection, actor_key, project_id, required=required)
        row = connection.execute(
            """
            SELECT s.*, COUNT(m.id) AS message_count, MAX(m.id) AS last_message_id
            FROM project_ai_sessions s
            LEFT JOIN project_ai_messages m
              ON m.session_id = s.id AND m.project_id = s.project_id
             AND m.actor_key = s.actor_key
            WHERE s.id = ? AND s.project_id = ? AND s.actor_key = ?
            GROUP BY s.id
            """,
            (str(session_id), project_id, actor_key),
        ).fetchone()
        if row is None:
            raise KeyError("AI session not found")
        return row

    def ensure_ai_session_capacity(self, actor_key, project_id, session_id=None):
        """Fail before inference when a new session or turn cannot be persisted."""
        with self._connect() as connection:
            if session_id:
                session_row = self._access_ai_session(
                    connection, actor_key, project_id, session_id, required="editor"
                )
                if int(session_row["message_count"]) + 2 > AI_SESSION_MESSAGE_LIMIT:
                    raise ValueError(
                        f"An AI session may contain at most "
                        f"{AI_SESSION_MESSAGE_LIMIT} messages"
                    )
                return
            self._access_project(connection, actor_key, project_id, required="editor")
            session_count = connection.execute(
                """SELECT COUNT(*) FROM project_ai_sessions
                   WHERE actor_key = ? AND project_id = ?""",
                (actor_key, project_id),
            ).fetchone()[0]
            if session_count >= AI_SESSION_LIMIT_PER_PROJECT:
                raise ValueError(
                    f"An account may have at most {AI_SESSION_LIMIT_PER_PROJECT} "
                    "AI sessions per project"
                )

    def create_ai_session(
        self,
        actor_key,
        project_id,
        title="New chat",
        *,
        backend="local",
        model="",
        session_id=None,
    ):
        """Create a private assistant session for an editor of a project."""
        if title is None or (isinstance(title, str) and not title.strip()):
            title = "New chat"
        title = self._ai_session_value(title, "title", AI_SESSION_TITLE_MAX_LENGTH)
        backend = self._ai_session_value(
            backend, "backend", AI_SESSION_BACKEND_MAX_LENGTH
        )
        model = self._ai_session_value(
            model, "model", AI_SESSION_MODEL_MAX_LENGTH, required=False
        )
        if session_id is None:
            session_id = str(uuid.uuid4())
        else:
            session_id = self._ai_session_value(session_id, "session_id", 36)
            try:
                parsed_session_id = uuid.UUID(session_id)
            except ValueError as exc:
                raise ValueError("session_id must be a UUID") from exc
            if str(parsed_session_id) != session_id.lower():
                raise ValueError("session_id must be a canonical UUID")
            session_id = str(parsed_session_id)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._access_project(connection, actor_key, project_id, required="editor")
            session_count = connection.execute(
                """SELECT COUNT(*) FROM project_ai_sessions
                   WHERE actor_key = ? AND project_id = ?""",
                (actor_key, project_id),
            ).fetchone()[0]
            if session_count >= AI_SESSION_LIMIT_PER_PROJECT:
                raise ValueError(
                    f"An account may have at most {AI_SESSION_LIMIT_PER_PROJECT} "
                    "AI sessions per project"
                )
            if connection.execute(
                "SELECT 1 FROM project_ai_sessions WHERE id = ?", (session_id,)
            ).fetchone():
                raise ValueError("The AI session identifier is unavailable")
            connection.execute(
                """
                INSERT INTO project_ai_sessions
                    (id, project_id, actor_key, title, backend, model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    project_id,
                    actor_key,
                    self._encrypt(title),
                    backend,
                    model,
                    now,
                    now,
                ),
            )
            row = self._access_ai_session(
                connection, actor_key, project_id, session_id, required="editor"
            )
        return self._row("project_ai_sessions", row)

    def ai_session_has_request(self, actor_key, project_id, session_id, request_id):
        """Return whether an idempotent turn request is already fully stored."""
        request_id = self._ai_session_value(request_id, "request_id", 100)
        with self._connect() as connection:
            self._access_ai_session(
                connection, actor_key, project_id, session_id, required="editor"
            )
            rows = connection.execute(
                """SELECT role FROM project_ai_messages
                   WHERE session_id = ? AND project_id = ? AND actor_key = ?
                     AND request_id = ?""",
                (str(session_id), project_id, actor_key, request_id),
            ).fetchall()
        if not rows:
            return False
        if len(rows) != 2 or {row["role"] for row in rows} != {"user", "assistant"}:
            raise ValueError("The AI turn request is incomplete")
        return True

    def list_ai_sessions(self, actor_key, project_id):
        """List only the current actor's sessions for an accessible project."""
        with self._connect() as connection:
            self._access_project(connection, actor_key, project_id, required="viewer")
            rows = connection.execute(
                """
                SELECT s.*, COUNT(m.id) AS message_count, MAX(m.id) AS last_message_id
                FROM project_ai_sessions s
                LEFT JOIN project_ai_messages m
                  ON m.session_id = s.id AND m.project_id = s.project_id
                 AND m.actor_key = s.actor_key
                WHERE s.actor_key = ? AND s.project_id = ?
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id
                """,
                (actor_key, project_id),
            ).fetchall()
        return self._rows("project_ai_sessions", rows)

    def get_ai_session(
        self,
        actor_key,
        project_id,
        session_id,
        *,
        message_limit=100,
        before_id=None,
    ):
        """Return private session metadata and one ascending page of its messages."""
        message_limit = self._ai_session_page_value(
            message_limit, "message_limit", AI_SESSION_PAGE_MAX_LENGTH
        )
        if before_id is not None:
            before_id = self._ai_session_page_value(
                before_id, "before_id", 9_223_372_036_854_775_807
            )
        with self._connect() as connection:
            session_row = self._access_ai_session(
                connection, actor_key, project_id, session_id, required="viewer"
            )
            parameters = [str(session_id), project_id, actor_key]
            before_clause = ""
            if before_id is not None:
                before_clause = " AND id < ?"
                parameters.append(before_id)
            parameters.append(message_limit + 1)
            rows = connection.execute(
                f"""
                SELECT * FROM project_ai_messages
                WHERE session_id = ? AND project_id = ? AND actor_key = ?{before_clause}
                ORDER BY id DESC LIMIT ?
                """,
                parameters,
            ).fetchall()
        has_more = len(rows) > message_limit
        rows = rows[:message_limit]
        messages = self._rows("project_ai_messages", reversed(rows))
        return {
            "session": self._row("project_ai_sessions", session_row),
            "messages": messages,
            "has_more": has_more,
            "next_before_id": messages[0]["id"] if has_more and messages else None,
        }

    def delete_ai_session(self, actor_key, project_id, session_id):
        """Delete only the current actor's session, even when the actor owns the project."""
        with self._connect() as connection:
            self._access_ai_session(
                connection, actor_key, project_id, session_id, required="viewer"
            )
            cursor = connection.execute(
                """DELETE FROM project_ai_sessions
                   WHERE id = ? AND project_id = ? AND actor_key = ?""",
                (str(session_id), project_id, actor_key),
            )
            if cursor.rowcount != 1:
                raise KeyError("AI session not found")

    def ai_session_model_history(
        self, actor_key, project_id, session_id, *, limit=12
    ):
        """Build trusted model history from encrypted server-side messages."""
        limit = self._ai_session_page_value(limit, "limit", 12)
        with self._connect() as connection:
            self._access_ai_session(
                connection, actor_key, project_id, session_id, required="viewer"
            )
            rows = connection.execute(
                """
                SELECT role, content, model_context FROM project_ai_messages
                WHERE session_id = ? AND project_id = ? AND actor_key = ?
                ORDER BY id DESC LIMIT ?
                """,
                (str(session_id), project_id, actor_key, limit),
            ).fetchall()
        history = []
        for row in reversed(rows):
            content = self._decrypt(row["content"])
            if row["role"] == "assistant":
                model_context = self._decrypt(row["model_context"])
                content = model_context or content
            history.append({"role": row["role"], "content": content})
        return history

    def append_ai_turn(
        self,
        actor_key,
        project_id,
        session_id,
        user_content,
        assistant_content,
        *,
        model_context="",
        model="",
        request_id=None,
    ):
        """Atomically persist both sides of one successful assistant turn."""
        user_content = self._ai_session_value(
            user_content, "user_content", AI_SESSION_MESSAGE_MAX_LENGTH
        )
        assistant_content = self._ai_session_value(
            assistant_content, "assistant_content", AI_SESSION_MESSAGE_MAX_LENGTH
        )
        if model_context is None or model_context == "":
            model_context = assistant_content
        model_context = self._ai_session_value(
            model_context,
            "model_context",
            AI_SESSION_CONTEXT_MAX_LENGTH,
        )
        model = self._ai_session_value(
            model, "model", AI_SESSION_MODEL_MAX_LENGTH, required=False
        )
        if request_id is None:
            request_id = str(uuid.uuid4())
        request_id = self._ai_session_value(request_id, "request_id", 100)
        turn_id = str(uuid.uuid4())
        now = self._now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session_row = self._access_ai_session(
                connection, actor_key, project_id, session_id, required="editor"
            )
            existing = connection.execute(
                """
                SELECT * FROM project_ai_messages
                WHERE session_id = ? AND project_id = ? AND actor_key = ?
                  AND request_id = ?
                ORDER BY id
                """,
                (str(session_id), project_id, actor_key, request_id),
            ).fetchall()
            if existing:
                if len(existing) != 2 or {row["role"] for row in existing} != {
                    "user", "assistant"
                }:
                    raise ValueError("The AI turn request is incomplete")
                existing_by_role = {row["role"]: row for row in existing}
                if (
                    self._decrypt(existing_by_role["user"]["content"]) != user_content
                    or self._decrypt(existing_by_role["assistant"]["content"])
                    != assistant_content
                    or self._decrypt(existing_by_role["assistant"]["model_context"])
                    != model_context
                ):
                    raise ValueError("request_id has already been used for another AI turn")
                saved_session = self._row("project_ai_sessions", session_row)
                return {
                    "session": saved_session,
                    "turn_id": existing[0]["turn_id"],
                    "messages": self._rows("project_ai_messages", existing),
                }

            message_count = int(session_row["message_count"])
            if message_count + 2 > AI_SESSION_MESSAGE_LIMIT:
                raise ValueError(
                    f"An AI session may contain at most {AI_SESSION_MESSAGE_LIMIT} messages"
                )
            pinned_model = str(session_row["model"] or "")
            if pinned_model and model and pinned_model != model:
                raise ValueError("The AI session is pinned to a different model")
            effective_model = pinned_model or model
            if not pinned_model and effective_model:
                connection.execute(
                    """UPDATE project_ai_sessions SET model = ?
                       WHERE id = ? AND project_id = ? AND actor_key = ?""",
                    (effective_model, str(session_id), project_id, actor_key),
                )

            rows = []
            for role, content, context, message_model in (
                ("user", user_content, "", ""),
                ("assistant", assistant_content, model_context, effective_model),
            ):
                cursor = connection.execute(
                    """
                    INSERT INTO project_ai_messages
                        (session_id, project_id, actor_key, turn_id, request_id, role,
                         content, model_context, model, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(session_id),
                        project_id,
                        actor_key,
                        turn_id,
                        request_id,
                        role,
                        self._encrypt(content),
                        self._encrypt(context),
                        message_model,
                        now,
                    ),
                )
                rows.append(connection.execute(
                    "SELECT * FROM project_ai_messages WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone())
            connection.execute(
                """UPDATE project_ai_sessions SET updated_at = ?
                   WHERE id = ? AND project_id = ? AND actor_key = ?""",
                (now, str(session_id), project_id, actor_key),
            )
            saved_session_row = self._access_ai_session(
                connection, actor_key, project_id, session_id, required="editor"
            )

        return {
            "session": self._row("project_ai_sessions", saved_session_row),
            "turn_id": turn_id,
            "messages": self._rows("project_ai_messages", rows),
        }

    def portfolio(self, actor_key):
        self.ensure_default_connections(actor_key)
        today = date.today().isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH accessible(project_id, access_role) AS (
                    SELECT id, 'owner' FROM projects WHERE owner_key = ?
                    UNION ALL
                    SELECT project_id, role FROM project_shares
                    WHERE member_owner_key = ? AND status = 'accepted'
                )
                SELECT p.*, a.access_role,
                       COALESCE(SUM(CASE WHEN r.status NOT IN ('done', 'resolved') THEN 1 ELSE 0 END), 0) AS open_items,
                       COALESCE(SUM(CASE WHEN r.due_date < ? AND r.status NOT IN ('done', 'resolved') THEN 1 ELSE 0 END), 0) AS overdue_items
                FROM accessible a
                JOIN projects p ON p.id = a.project_id
                LEFT JOIN project_records r ON r.project_id = p.id
                WHERE p.status != 'archived'
                GROUP BY p.id, a.access_role
                ORDER BY
                    CASE p.status WHEN 'active' THEN 0 WHEN 'planned' THEN 1 WHEN 'on_hold' THEN 2 ELSE 3 END,
                    p.target_date IS NULL, p.target_date, p.name
                """,
                (actor_key, actor_key, today),
            ).fetchall()
            projects = self._rows("projects", rows)
            project_ids = [project["id"] for project in projects]
            overdue = 0
            open_raid = 0
            if project_ids:
                placeholders = ",".join("?" for _ in project_ids)
                overdue = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM project_records
                    WHERE project_id IN ({placeholders}) AND due_date < ?
                      AND status NOT IN ('done', 'resolved')
                    """,
                    (*project_ids, today),
                ).fetchone()[0]
                open_raid = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM project_records
                    WHERE project_id IN ({placeholders}) AND kind IN ('risk', 'issue')
                      AND status NOT IN ('done', 'resolved')
                    """,
                    project_ids,
                ).fetchone()[0]
            connections = connection.execute(
                """
                SELECT * FROM project_connections
                WHERE owner_key = ? AND project_id IS NULL
                ORDER BY label COLLATE NOCASE
                """,
                (actor_key,),
            ).fetchall()

        summary = {
            "total_projects": len(projects),
            "active_projects": sum(project["status"] == "active" for project in projects),
            "at_risk_projects": sum(project["health"] == "at_risk" for project in projects),
            "off_track_projects": sum(project["health"] == "off_track" for project in projects),
            "overdue_items": overdue,
            "open_raid": open_raid,
        }
        return {
            "summary": summary,
            "projects": projects,
            "connections": self._rows("project_connections", connections),
        }

    def workspace(self, actor_key, project_id):
        with self._connect() as connection:
            # Keep every collection in one read snapshot. AI previews sign a version
            # of this workspace, so mixing rows from different commits would make the
            # proposal context and its freshness token disagree.
            connection.execute("BEGIN")
            access = self._access_project(connection, actor_key, project_id)
            project_owner = access["owner_key"]
            project_row = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, project_owner),
            ).fetchone()
            records = connection.execute(
                """
                SELECT * FROM project_records WHERE owner_key = ? AND project_id = ?
                ORDER BY
                    CASE status WHEN 'blocked' THEN 0 WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END,
                    due_date IS NULL, due_date, created_at DESC
                """,
                (project_owner, project_id),
            ).fetchall()
            meetings = connection.execute(
                """
                SELECT * FROM project_meetings WHERE owner_key = ? AND project_id = ?
                ORDER BY held_on DESC, id DESC
                """,
                (project_owner, project_id),
            ).fetchall()
            stakeholders = connection.execute(
                """
                SELECT * FROM project_stakeholders WHERE owner_key = ? AND project_id = ?
                ORDER BY CASE influence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, name
                """,
                (project_owner, project_id),
            ).fetchall()
            if access["access_role"] == "owner":
                connections = connection.execute(
                    """
                    SELECT * FROM project_connections
                    WHERE owner_key = ? AND (project_id IS NULL OR project_id = ?)
                    ORDER BY project_id IS NOT NULL DESC, label COLLATE NOCASE
                    """,
                    (project_owner, project_id),
                ).fetchall()
                shares = connection.execute(
                    """
                    SELECT id, project_id, owner_key, invited_email, invited_by_email,
                           member_owner_key, role, status, expires_at, accepted_at,
                           created_at, updated_at
                    FROM project_shares WHERE project_id = ? AND owner_key = ?
                    ORDER BY status = 'accepted' DESC, invited_email_hash
                    """,
                    (project_id, project_owner),
                ).fetchall()
            else:
                connections = connection.execute(
                    """
                    SELECT * FROM project_connections
                    WHERE owner_key = ? AND project_id = ?
                    ORDER BY label COLLATE NOCASE
                    """,
                    (project_owner, project_id),
                ).fetchall()
                shares = []

        project = self._row("projects", project_row)
        project["access_role"] = access["access_role"]
        project["is_owner"] = access["access_role"] == "owner"
        permissions = {
            "role": access["access_role"],
            "can_edit": ACCESS_LEVELS[access["access_role"]] >= ACCESS_LEVELS["editor"],
            "can_share": access["access_role"] == "owner",
            "can_delete": access["access_role"] == "owner",
        }
        return {
            "project": project,
            "permissions": permissions,
            "records": self._rows("project_records", records),
            "meetings": self._rows("project_meetings", meetings),
            "stakeholders": self._rows("project_stakeholders", stakeholders),
            "connections": self._rows("project_connections", connections),
            "shares": self._rows("project_shares", shares),
        }

    def create_project(self, owner_key, values):
        now = self._now()
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO projects
                        (owner_key, name, code, description, status, priority, health, manager,
                         sponsor, start_date, target_date, budget, progress, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        owner_key, values["name"], values["code"],
                        self._encrypt(values.get("description", "")), values["status"],
                        values["priority"], values["health"], values.get("manager", ""),
                        values.get("sponsor", ""), values.get("start_date"),
                        values.get("target_date"), values.get("budget", 0),
                        values.get("progress", 0), now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A project with that code already exists") from exc
            project_id = cursor.lastrowid
        return self.workspace(owner_key, project_id)["project"]

    def update_project(self, actor_key, project_id, values):
        fields = (
            "name", "code", "description", "status", "priority", "health", "manager",
            "sponsor", "start_date", "target_date", "budget", "progress",
        )
        updates = {key: values[key] for key in fields if key in values}
        if "description" in updates:
            updates["description"] = self._encrypt(updates["description"])
        updates["updated_at"] = self._now()
        with self._connect() as connection:
            access = self._access_project(connection, actor_key, project_id, required="editor")
            project_owner = access["owner_key"]
            current = connection.execute(
                "SELECT start_date, target_date FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, project_owner),
            ).fetchone()
            start_date = updates.get("start_date", current["start_date"])
            target_date = updates.get("target_date", current["target_date"])
            if start_date and target_date and target_date < start_date:
                raise ValueError("target_date cannot be before start_date")
            assignments = ", ".join(f"{field} = ?" for field in updates)
            try:
                connection.execute(
                    f"UPDATE projects SET {assignments} WHERE id = ? AND owner_key = ?",
                    (*updates.values(), project_id, project_owner),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A project with that code already exists") from exc
        return self.workspace(actor_key, project_id)["project"]

    def delete_project(self, actor_key, project_id):
        with self._connect() as connection:
            access = self._owned_project(connection, actor_key, project_id)
            connection.execute(
                "DELETE FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, access["owner_key"]),
            )

    @staticmethod
    def _ai_proposal_expiry(proposal):
        value = proposal.get("expires_at")
        if not isinstance(value, str):
            raise ValueError("The assistant proposal is missing an expiration time")
        try:
            expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("The assistant proposal has an invalid expiration time") from exc
        if expires_at.tzinfo is None:
            raise ValueError("The assistant proposal has an invalid expiration time")
        return expires_at.astimezone(UTC)

    @staticmethod
    def _ai_expected_state(proposal):
        expected = proposal.get("expected_state")
        if not isinstance(expected, dict):
            raise ValueError("The assistant proposal is missing its expected project state")
        project_updated_at = expected.get("project_updated_at")
        records_updated_at = expected.get("records_updated_at")
        workspace_version = expected.get("workspace_version")
        if (
            not isinstance(project_updated_at, str)
            or not isinstance(records_updated_at, dict)
            or not isinstance(workspace_version, str)
            or len(workspace_version) != 64
        ):
            raise ValueError("The assistant proposal has an invalid expected project state")
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in records_updated_at.items()):
            raise ValueError("The assistant proposal has an invalid expected project state")
        return project_updated_at, records_updated_at, workspace_version

    @staticmethod
    def ai_workspace_version(workspace):
        version_state = {
            "project_updated_at": (workspace.get("project") or {}).get("updated_at"),
        }
        for collection in ("records", "meetings", "stakeholders", "connections"):
            version_state[collection] = sorted(
                [
                    [item.get("id"), item.get("updated_at")]
                    for item in workspace.get(collection, [])
                    if isinstance(item, dict)
                ],
                key=lambda item: (item[0] is None, item[0]),
            )
        canonical = json.dumps(
            version_state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _ai_current_workspace_version(self, connection, access, project_id, project_updated_at):
        project_owner = access["owner_key"]
        workspace = {
            "project": {"updated_at": project_updated_at},
        }
        for collection, table in (
            ("records", "project_records"),
            ("meetings", "project_meetings"),
            ("stakeholders", "project_stakeholders"),
        ):
            workspace[collection] = [
                dict(row) for row in connection.execute(
                    f"SELECT id, updated_at FROM {table} WHERE project_id = ? AND owner_key = ?",
                    (project_id, project_owner),
                ).fetchall()
            ]
        if access["access_role"] == "owner":
            connection_rows = connection.execute(
                """SELECT id, updated_at FROM project_connections
                   WHERE owner_key = ? AND (project_id IS NULL OR project_id = ?)""",
                (project_owner, project_id),
            ).fetchall()
        else:
            connection_rows = connection.execute(
                """SELECT id, updated_at FROM project_connections
                   WHERE owner_key = ? AND project_id = ?""",
                (project_owner, project_id),
            ).fetchall()
        workspace["connections"] = [dict(row) for row in connection_rows]
        return self.ai_workspace_version(workspace)

    @staticmethod
    def _ai_audit_actions(actions):
        serialized = json.dumps(actions, ensure_ascii=False)
        if len(serialized) <= 100_000:
            return serialized
        summaries = []
        for action in actions[:25]:
            if not isinstance(action, dict):
                continue
            fields = action.get("fields") if isinstance(action.get("fields"), dict) else {}
            summaries.append({
                "type": action.get("type"),
                "record_id": action.get("record_id"),
                "reason": str(action.get("reason") or "")[:500],
                "evidence_refs": action.get("evidence_refs", [])[:12]
                if isinstance(action.get("evidence_refs"), list) else [],
                "field_names": sorted(str(key) for key in fields),
            })
        return json.dumps({
            "truncated": True,
            "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "action_count": len(actions),
            "actions": summaries,
        }, ensure_ascii=False)

    def apply_ai_actions(
        self,
        actor_key,
        project_id,
        proposal,
        signature,
        actions,
        selected_action_indexes=None,
    ):
        """Apply a signed, prevalidated proposal atomically and exactly once."""
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        references = []
        with self._connect() as connection:
            # Reserve the write transaction before reading the expected versions so another
            # writer cannot change them between the checks and the mutations below.
            connection.execute("BEGIN IMMEDIATE")
            access = self._access_project(connection, actor_key, project_id, required="editor")
            project_owner = access["owner_key"]
            if connection.execute(
                "SELECT 1 FROM project_ai_audit WHERE proposal_signature = ?", (signature,)
            ).fetchone():
                raise ValueError("This assistant proposal has already been applied")

            if self._ai_proposal_expiry(proposal) <= now_value:
                raise ValueError("This assistant proposal has expired; request a new preview")
            (
                expected_project_version,
                expected_record_versions,
                expected_workspace_version,
            ) = self._ai_expected_state(proposal)
            current_project = connection.execute(
                """SELECT start_date, target_date, updated_at FROM projects
                   WHERE id = ? AND owner_key = ?""",
                (project_id, project_owner),
            ).fetchone()
            if current_project["updated_at"] != expected_project_version:
                raise ValueError(
                    "The project changed after this assistant preview; request a new preview"
                )
            target_record_ids = {
                record_id for action_type, record_id, _values in actions
                if action_type == "update_record"
            }
            for record_id in target_record_ids:
                expected_version = expected_record_versions.get(str(record_id))
                if expected_version is None:
                    raise ValueError(
                        "The assistant proposal is missing an expected record state"
                    )
                current_record = connection.execute(
                    """SELECT updated_at FROM project_records
                       WHERE id = ? AND project_id = ? AND owner_key = ?""",
                    (record_id, project_id, project_owner),
                ).fetchone()
                if current_record is None or current_record["updated_at"] != expected_version:
                    raise ValueError(
                        "A project record changed after this assistant preview; request a new preview"
                    )
            if self._ai_current_workspace_version(
                connection, access, project_id, current_project["updated_at"]
            ) != expected_workspace_version:
                raise ValueError(
                    "The project workspace changed after this assistant preview; request a new preview"
                )

            for action_type, record_id, values in actions:
                if action_type == "update_project":
                    updates = dict(values)
                    if "target_date" in updates:
                        current = current_project
                        if current and current["start_date"] and updates["target_date"]:
                            if updates["target_date"] < current["start_date"]:
                                raise ValueError("target_date cannot be before start_date")
                    if "description" in updates:
                        updates["description"] = self._encrypt(updates["description"])
                    updates["updated_at"] = now
                    assignments = ", ".join(f"{field} = ?" for field in updates)
                    connection.execute(
                        f"UPDATE projects SET {assignments} WHERE id = ? AND owner_key = ?",
                        (*updates.values(), project_id, project_owner),
                    )
                    references.append({"type": action_type, "id": project_id})
                elif action_type == "create_record":
                    cursor = connection.execute(
                        """
                        INSERT INTO project_records
                            (owner_key, project_id, kind, title, details, status, priority, owner,
                             due_date, resolution, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project_owner, project_id, values["kind"], values["title"],
                            self._encrypt(values.get("details", "")), values["status"], values["priority"],
                            values.get("owner", ""), values.get("due_date"),
                            self._encrypt(values.get("resolution", "")), now, now,
                        ),
                    )
                    references.append({"type": action_type, "id": cursor.lastrowid})
                elif action_type == "update_record":
                    updates = dict(values)
                    for field in ("details", "resolution"):
                        if field in updates:
                            updates[field] = self._encrypt(updates[field])
                    updates["updated_at"] = now
                    assignments = ", ".join(f"{field} = ?" for field in updates)
                    cursor = connection.execute(
                        f"""UPDATE project_records SET {assignments}
                            WHERE id = ? AND project_id = ? AND owner_key = ?""",
                        (*updates.values(), record_id, project_id, project_owner),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Assistant proposal references a record outside this project")
                    references.append({"type": action_type, "id": record_id})
                elif action_type == "create_meeting":
                    cursor = connection.execute(
                        """
                        INSERT INTO project_meetings
                            (owner_key, project_id, title, held_on, attendees, notes, decisions,
                             action_items, next_steps, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project_owner, project_id, values["title"], values["held_on"],
                            self._encrypt(values.get("attendees", "")),
                            self._encrypt(values.get("notes", "")),
                            self._encrypt(values.get("decisions", "")),
                            self._encrypt(values.get("action_items", "")),
                            self._encrypt(values.get("next_steps", "")), now, now,
                        ),
                    )
                    references.append({"type": action_type, "id": cursor.lastrowid})

            connection.execute(
                """
                INSERT INTO project_ai_audit
                    (project_id, owner_key, actor_key, model, summary, actions,
                     applied_count, proposal_signature, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    project_owner,
                    actor_key,
                    str(proposal.get("model", ""))[:100],
                    self._encrypt(str(proposal.get("summary", ""))[:5000]),
                    self._encrypt(self._ai_audit_actions(
                        proposal.get("actions", [])
                        if selected_action_indexes is None
                        else [proposal["actions"][index] for index in selected_action_indexes]
                    )),
                    len(references),
                    signature,
                    now,
                ),
            )
        return references

    def create_record(self, actor_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            access = self._access_project(connection, actor_key, project_id, required="editor")
            project_owner = access["owner_key"]
            cursor = connection.execute(
                """
                INSERT INTO project_records
                    (owner_key, project_id, kind, title, details, status, priority, owner,
                     due_date, resolution, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_owner, project_id, values["kind"], values["title"],
                    self._encrypt(values.get("details", "")), values["status"], values["priority"],
                    values.get("owner", ""), values.get("due_date"),
                    self._encrypt(values.get("resolution", "")), now, now,
                ),
            )
            record_id = cursor.lastrowid
        return self._get_child("project_records", actor_key, record_id)

    def update_record(self, actor_key, record_id, values):
        return self._update_child(
            "project_records", actor_key, record_id, values,
            {"kind", "title", "details", "status", "priority", "owner", "due_date", "resolution"},
        )

    def delete_record(self, actor_key, record_id):
        self._delete_child("project_records", actor_key, record_id)

    def create_meeting(self, actor_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            access = self._access_project(connection, actor_key, project_id, required="editor")
            project_owner = access["owner_key"]
            cursor = connection.execute(
                """
                INSERT INTO project_meetings
                    (owner_key, project_id, title, held_on, attendees, notes, decisions,
                     action_items, next_steps, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_owner, project_id, values["title"], values["held_on"],
                    self._encrypt(values.get("attendees", "")), self._encrypt(values.get("notes", "")),
                    self._encrypt(values.get("decisions", "")), self._encrypt(values.get("action_items", "")),
                    self._encrypt(values.get("next_steps", "")), now, now,
                ),
            )
            meeting_id = cursor.lastrowid
        return self._get_child("project_meetings", actor_key, meeting_id)

    def update_meeting(self, actor_key, meeting_id, values):
        return self._update_child(
            "project_meetings", actor_key, meeting_id, values,
            {"title", "held_on", "attendees", "notes", "decisions", "action_items", "next_steps"},
        )

    def delete_meeting(self, actor_key, meeting_id):
        self._delete_child("project_meetings", actor_key, meeting_id)

    def create_stakeholder(self, actor_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            access = self._access_project(connection, actor_key, project_id, required="editor")
            project_owner = access["owner_key"]
            cursor = connection.execute(
                """
                INSERT INTO project_stakeholders
                    (owner_key, project_id, name, role, email, influence, engagement, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_owner, project_id, values["name"], values.get("role", ""),
                    values.get("email", ""), values["influence"], values["engagement"],
                    self._encrypt(values.get("notes", "")), now, now,
                ),
            )
            stakeholder_id = cursor.lastrowid
        return self._get_child("project_stakeholders", actor_key, stakeholder_id)

    def update_stakeholder(self, actor_key, stakeholder_id, values):
        return self._update_child(
            "project_stakeholders", actor_key, stakeholder_id, values,
            {"name", "role", "email", "influence", "engagement", "notes"},
        )

    def delete_stakeholder(self, actor_key, stakeholder_id):
        self._delete_child("project_stakeholders", actor_key, stakeholder_id)

    def create_connection(self, actor_key, values):
        now = self._now()
        project_id = values.get("project_id")
        with self._connect() as connection:
            if project_id is None:
                connection_owner = actor_key
            else:
                access = self._access_project(connection, actor_key, project_id, required="owner")
                connection_owner = access["owner_key"]
            cursor = connection.execute(
                """
                INSERT INTO project_connections
                    (owner_key, project_id, provider, label, account, url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_owner, project_id, values["provider"], values["label"],
                    self._encrypt(values.get("account", "")), values["url"], now, now,
                ),
            )
            connection_id = cursor.lastrowid
        return self._get_child("project_connections", actor_key, connection_id)

    def update_connection(self, actor_key, connection_id, values):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM project_connections WHERE id = ?",
                (connection_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Project item not found")
        if "project_id" in values and values["project_id"] != row["project_id"]:
            raise ValueError("Connection scope cannot be changed after creation")
        values = {key: value for key, value in values.items() if key != "project_id"}
        return self._update_child(
            "project_connections", actor_key, connection_id, values,
            {"provider", "label", "account", "url"},
            required="owner",
        )

    def delete_connection(self, actor_key, connection_id):
        self._delete_child("project_connections", actor_key, connection_id, required="owner")

    def create_share(self, actor_key, inviter_email, project_id, invited_email, role):
        normalized_email = self._normalize_email(invited_email)
        if not normalized_email:
            raise ValueError("An invited email is required")
        if role not in {"viewer", "editor"}:
            raise ValueError("Share role must be viewer or editor")
        if normalized_email == self._normalize_email(inviter_email):
            raise ValueError("You already own this project")
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        expires_at = (now_value + INVITATION_LIFETIME).isoformat()
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        email_hash = self._email_hash(normalized_email)
        with self._connect() as connection:
            access = self._owned_project(connection, actor_key, project_id)
            project_owner = access["owner_key"]
            existing = connection.execute(
                "SELECT id, status FROM project_shares WHERE project_id = ? AND invited_email_hash = ?",
                (project_id, email_hash),
            ).fetchone()
            if existing is not None and existing["status"] == "accepted":
                connection.execute(
                    "UPDATE project_shares SET role = ?, updated_at = ? WHERE id = ?",
                    (role, now, existing["id"]),
                )
                return {"share": self._get_share(connection, project_owner, existing["id"]), "token": None}
            encrypted_email = self._encrypt(normalized_email)
            encrypted_inviter = self._encrypt(self._normalize_email(inviter_email))
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO project_shares
                        (project_id, owner_key, invited_email_hash, invited_email, invited_by_email,
                         role, status, token_hash, expires_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        project_id, project_owner, email_hash, encrypted_email, encrypted_inviter,
                        role, token_hash, expires_at, now, now,
                    ),
                )
                share_id = cursor.lastrowid
            else:
                share_id = existing["id"]
                connection.execute(
                    """
                    UPDATE project_shares
                    SET invited_email = ?, invited_by_email = ?, member_owner_key = NULL,
                        role = ?, status = 'pending', token_hash = ?, expires_at = ?,
                        accepted_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        encrypted_email, encrypted_inviter, role, token_hash,
                        expires_at, now, share_id,
                    ),
                )
            share = self._get_share(connection, project_owner, share_id)
        return {"share": share, "token": token}

    def update_share(self, actor_key, share_id, role):
        if role not in {"viewer", "editor"}:
            raise ValueError("Share role must be viewer or editor")
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id, owner_key FROM project_shares WHERE id = ?",
                (share_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Project invitation not found")
            self._owned_project(connection, actor_key, row["project_id"])
            connection.execute(
                "UPDATE project_shares SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, share_id),
            )
            return self._get_share(connection, row["owner_key"], share_id)

    def delete_share(self, actor_key, share_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM project_shares WHERE id = ?",
                (share_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Project invitation not found")
            self._owned_project(connection, actor_key, row["project_id"])
            connection.execute("DELETE FROM project_shares WHERE id = ?", (share_id,))

    def invitation(self, token, invited_email):
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.project_id, s.invited_email, s.invited_by_email,
                       s.role, s.status, s.expires_at, p.name AS project_name, p.code AS project_code
                FROM project_shares s JOIN projects p ON p.id = s.project_id
                WHERE s.token_hash = ? AND s.invited_email_hash = ?
                  AND s.status = 'pending' AND s.expires_at > ?
                """,
                (self._token_hash(token), self._email_hash(invited_email), now),
            ).fetchone()
        if row is None:
            raise KeyError("Invitation not found, expired, or intended for another account")
        return self._row("project_shares", row)

    def accept_invitation(self, token, actor_key, invited_email):
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.project_id, p.owner_key
                FROM project_shares s JOIN projects p ON p.id = s.project_id
                WHERE s.token_hash = ? AND s.invited_email_hash = ?
                  AND s.status = 'pending' AND s.expires_at > ?
                """,
                (self._token_hash(token), self._email_hash(invited_email), now),
            ).fetchone()
            if row is None:
                raise KeyError("Invitation not found, expired, or intended for another account")
            if row["owner_key"] == actor_key:
                raise ValueError("You already own this project")
            connection.execute(
                """
                UPDATE project_shares
                SET status = 'accepted', member_owner_key = ?, accepted_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (actor_key, now, now, row["id"]),
            )
            return row["project_id"]

    def _get_share(self, connection, owner_key, share_id):
        row = connection.execute(
            """
            SELECT id, project_id, owner_key, invited_email, invited_by_email,
                   member_owner_key, role, status, expires_at, accepted_at,
                   created_at, updated_at
            FROM project_shares WHERE id = ? AND owner_key = ?
            """,
            (share_id, owner_key),
        ).fetchone()
        if row is None:
            raise KeyError("Project invitation not found")
        return self._row("project_shares", row)

    def _get_child(self, table, actor_key, item_id):
        if table not in CHILD_TABLES:
            raise ValueError("Unsupported project table")
        with self._connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise KeyError("Project item not found")
            if table == "project_connections" and row["project_id"] is None:
                if row["owner_key"] != actor_key:
                    raise KeyError("Project item not found")
            else:
                self._access_project(connection, actor_key, row["project_id"])
        return self._row(table, row)

    def _update_child(
        self, table, actor_key, item_id, values, allowed_fields, required="editor"
    ):
        if table not in CHILD_TABLES:
            raise ValueError("Unsupported project table")
        updates = {key: values[key] for key in allowed_fields if key in values}
        for field in ENCRYPTED_FIELDS[table]:
            if field in updates:
                updates[field] = self._encrypt(updates[field])
        updates["updated_at"] = self._now()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        with self._connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise KeyError("Project item not found")
            if table == "project_connections" and row["project_id"] is None:
                if row["owner_key"] != actor_key:
                    raise KeyError("Project item not found")
            else:
                self._access_project(connection, actor_key, row["project_id"], required=required)
            connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ? AND owner_key = ?",
                (*updates.values(), item_id, row["owner_key"]),
            )
        return self._get_child(table, actor_key, item_id)

    def _delete_child(self, table, actor_key, item_id, required="editor"):
        if table not in CHILD_TABLES:
            raise ValueError("Unsupported project table")
        with self._connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise KeyError("Project item not found")
            if table == "project_connections" and row["project_id"] is None:
                if row["owner_key"] != actor_key:
                    raise KeyError("Project item not found")
            else:
                self._access_project(connection, actor_key, row["project_id"], required=required)
            connection.execute(
                f"DELETE FROM {table} WHERE id = ? AND owner_key = ?",
                (item_id, row["owner_key"]),
            )
