import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime

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
}


class ProjectStore:
    """User-scoped project portfolio stored in SQLite with encrypted notes."""

    def __init__(self, config):
        self.logger = GlobalLogger.get_logger("ProjectStore")
        key = config.get("Database", "encryption_key")
        if not key:
            key = Fernet.generate_key().decode("ascii")
            config.set("Database", "encryption_key", key)
        self.fernet = Fernet(key.encode("ascii"))

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
                """
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
            # Existing plaintext values remain readable if encryption was introduced later.
            return value

    def _row(self, table, row):
        if row is None:
            return None
        result = dict(row)
        for field in ENCRYPTED_FIELDS.get(table, set()):
            if field in result:
                result[field] = self._decrypt(result[field])
        return result

    def _rows(self, table, rows):
        return [self._row(table, row) for row in rows]

    def _owned_project(self, connection, owner_key, project_id):
        row = connection.execute(
            "SELECT id FROM projects WHERE id = ? AND owner_key = ?",
            (project_id, owner_key),
        ).fetchone()
        if row is None:
            raise KeyError("Project not found")

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

    def portfolio(self, owner_key):
        self.ensure_default_connections(owner_key)
        today = date.today().isoformat()
        with self._connect() as connection:
            projects = connection.execute(
                """
                SELECT p.*,
                       COALESCE(SUM(CASE WHEN r.status NOT IN ('done', 'resolved') THEN 1 ELSE 0 END), 0) AS open_items,
                       COALESCE(SUM(CASE WHEN r.due_date < ? AND r.status NOT IN ('done', 'resolved') THEN 1 ELSE 0 END), 0) AS overdue_items
                FROM projects p
                LEFT JOIN project_records r
                    ON r.project_id = p.id AND r.owner_key = p.owner_key
                WHERE p.owner_key = ? AND p.status != 'archived'
                GROUP BY p.id
                ORDER BY
                    CASE p.status WHEN 'active' THEN 0 WHEN 'planned' THEN 1 WHEN 'on_hold' THEN 2 ELSE 3 END,
                    p.target_date IS NULL,
                    p.target_date,
                    p.name
                """,
                (today, owner_key),
            ).fetchall()
            summary = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_projects,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_projects,
                    SUM(CASE WHEN health = 'at_risk' THEN 1 ELSE 0 END) AS at_risk_projects,
                    SUM(CASE WHEN health = 'off_track' THEN 1 ELSE 0 END) AS off_track_projects
                FROM projects WHERE owner_key = ? AND status != 'archived'
                """,
                (owner_key,),
            ).fetchone()
            overdue = connection.execute(
                """
                SELECT COUNT(*) FROM project_records
                WHERE owner_key = ? AND due_date < ? AND status NOT IN ('done', 'resolved')
                """,
                (owner_key, today),
            ).fetchone()[0]
            open_raid = connection.execute(
                """
                SELECT COUNT(*) FROM project_records
                WHERE owner_key = ? AND kind IN ('risk', 'issue') AND status NOT IN ('done', 'resolved')
                """,
                (owner_key,),
            ).fetchone()[0]
            connections = connection.execute(
                """
                SELECT * FROM project_connections
                WHERE owner_key = ? AND project_id IS NULL
                ORDER BY label COLLATE NOCASE
                """,
                (owner_key,),
            ).fetchall()
        summary_result = dict(summary)
        summary_result["overdue_items"] = overdue
        summary_result["open_raid"] = open_raid
        return {
            "summary": {key: value or 0 for key, value in summary_result.items()},
            "projects": self._rows("projects", projects),
            "connections": self._rows("project_connections", connections),
        }

    def workspace(self, owner_key, project_id):
        with self._connect() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, owner_key),
            ).fetchone()
            if project_row is None:
                raise KeyError("Project not found")
            records = connection.execute(
                """
                SELECT * FROM project_records WHERE owner_key = ? AND project_id = ?
                ORDER BY
                    CASE status WHEN 'blocked' THEN 0 WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END,
                    due_date IS NULL, due_date, created_at DESC
                """,
                (owner_key, project_id),
            ).fetchall()
            meetings = connection.execute(
                """
                SELECT * FROM project_meetings WHERE owner_key = ? AND project_id = ?
                ORDER BY held_on DESC, id DESC
                """,
                (owner_key, project_id),
            ).fetchall()
            stakeholders = connection.execute(
                """
                SELECT * FROM project_stakeholders WHERE owner_key = ? AND project_id = ?
                ORDER BY CASE influence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, name
                """,
                (owner_key, project_id),
            ).fetchall()
            connections = connection.execute(
                """
                SELECT * FROM project_connections
                WHERE owner_key = ? AND (project_id IS NULL OR project_id = ?)
                ORDER BY project_id IS NOT NULL DESC, label COLLATE NOCASE
                """,
                (owner_key, project_id),
            ).fetchall()
        return {
            "project": self._row("projects", project_row),
            "records": self._rows("project_records", records),
            "meetings": self._rows("project_meetings", meetings),
            "stakeholders": self._rows("project_stakeholders", stakeholders),
            "connections": self._rows("project_connections", connections),
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
                        owner_key,
                        values["name"],
                        values["code"],
                        self._encrypt(values.get("description", "")),
                        values["status"],
                        values["priority"],
                        values["health"],
                        values.get("manager", ""),
                        values.get("sponsor", ""),
                        values.get("start_date"),
                        values.get("target_date"),
                        values.get("budget", 0),
                        values.get("progress", 0),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A project with that code already exists") from exc
            project_id = cursor.lastrowid
        return self.workspace(owner_key, project_id)["project"]

    def update_project(self, owner_key, project_id, values):
        fields = (
            "name", "code", "description", "status", "priority", "health", "manager",
            "sponsor", "start_date", "target_date", "budget", "progress",
        )
        updates = {key: values[key] for key in fields if key in values}
        if "description" in updates:
            updates["description"] = self._encrypt(updates["description"])
        updates["updated_at"] = self._now()
        with self._connect() as connection:
            self._owned_project(connection, owner_key, project_id)
            current = connection.execute(
                "SELECT start_date, target_date FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, owner_key),
            ).fetchone()
            start_date = updates.get("start_date", current["start_date"])
            target_date = updates.get("target_date", current["target_date"])
            if start_date and target_date and target_date < start_date:
                raise ValueError("target_date cannot be before start_date")
            assignments = ", ".join(f"{field} = ?" for field in updates)
            try:
                connection.execute(
                    f"UPDATE projects SET {assignments} WHERE id = ? AND owner_key = ?",
                    (*updates.values(), project_id, owner_key),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A project with that code already exists") from exc
        return self.workspace(owner_key, project_id)["project"]

    def delete_project(self, owner_key, project_id):
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM projects WHERE id = ? AND owner_key = ?",
                (project_id, owner_key),
            )
            if cursor.rowcount == 0:
                raise KeyError("Project not found")

    def create_record(self, owner_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            self._owned_project(connection, owner_key, project_id)
            cursor = connection.execute(
                """
                INSERT INTO project_records
                    (owner_key, project_id, kind, title, details, status, priority, owner,
                     due_date, resolution, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_key, project_id, values["kind"], values["title"],
                    self._encrypt(values.get("details", "")), values["status"], values["priority"],
                    values.get("owner", ""), values.get("due_date"),
                    self._encrypt(values.get("resolution", "")), now, now,
                ),
            )
            record_id = cursor.lastrowid
        return self._get_child("project_records", owner_key, record_id)

    def update_record(self, owner_key, record_id, values):
        return self._update_child(
            "project_records",
            owner_key,
            record_id,
            values,
            {"kind", "title", "details", "status", "priority", "owner", "due_date", "resolution"},
        )

    def delete_record(self, owner_key, record_id):
        self._delete_child("project_records", owner_key, record_id)

    def create_meeting(self, owner_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            self._owned_project(connection, owner_key, project_id)
            cursor = connection.execute(
                """
                INSERT INTO project_meetings
                    (owner_key, project_id, title, held_on, attendees, notes, decisions,
                     action_items, next_steps, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_key, project_id, values["title"], values["held_on"],
                    self._encrypt(values.get("attendees", "")), self._encrypt(values.get("notes", "")),
                    self._encrypt(values.get("decisions", "")), self._encrypt(values.get("action_items", "")),
                    self._encrypt(values.get("next_steps", "")), now, now,
                ),
            )
            meeting_id = cursor.lastrowid
        return self._get_child("project_meetings", owner_key, meeting_id)

    def update_meeting(self, owner_key, meeting_id, values):
        return self._update_child(
            "project_meetings",
            owner_key,
            meeting_id,
            values,
            {"title", "held_on", "attendees", "notes", "decisions", "action_items", "next_steps"},
        )

    def delete_meeting(self, owner_key, meeting_id):
        self._delete_child("project_meetings", owner_key, meeting_id)

    def create_stakeholder(self, owner_key, project_id, values):
        now = self._now()
        with self._connect() as connection:
            self._owned_project(connection, owner_key, project_id)
            cursor = connection.execute(
                """
                INSERT INTO project_stakeholders
                    (owner_key, project_id, name, role, email, influence, engagement, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_key, project_id, values["name"], values.get("role", ""),
                    values.get("email", ""), values["influence"], values["engagement"],
                    self._encrypt(values.get("notes", "")), now, now,
                ),
            )
            stakeholder_id = cursor.lastrowid
        return self._get_child("project_stakeholders", owner_key, stakeholder_id)

    def update_stakeholder(self, owner_key, stakeholder_id, values):
        return self._update_child(
            "project_stakeholders",
            owner_key,
            stakeholder_id,
            values,
            {"name", "role", "email", "influence", "engagement", "notes"},
        )

    def delete_stakeholder(self, owner_key, stakeholder_id):
        self._delete_child("project_stakeholders", owner_key, stakeholder_id)

    def create_connection(self, owner_key, values):
        now = self._now()
        project_id = values.get("project_id")
        with self._connect() as connection:
            if project_id is not None:
                self._owned_project(connection, owner_key, project_id)
            cursor = connection.execute(
                """
                INSERT INTO project_connections
                    (owner_key, project_id, provider, label, account, url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_key, project_id, values["provider"], values["label"],
                    self._encrypt(values.get("account", "")), values["url"], now, now,
                ),
            )
            connection_id = cursor.lastrowid
        return self._get_child("project_connections", owner_key, connection_id)

    def update_connection(self, owner_key, connection_id, values):
        if "project_id" in values and values["project_id"] is not None:
            with self._connect() as connection:
                self._owned_project(connection, owner_key, values["project_id"])
        return self._update_child(
            "project_connections",
            owner_key,
            connection_id,
            values,
            {"project_id", "provider", "label", "account", "url"},
        )

    def delete_connection(self, owner_key, connection_id):
        self._delete_child("project_connections", owner_key, connection_id)

    def _get_child(self, table, owner_key, item_id):
        if table not in ENCRYPTED_FIELDS:
            raise ValueError("Unsupported project table")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE id = ? AND owner_key = ?",
                (item_id, owner_key),
            ).fetchone()
        if row is None:
            raise KeyError("Project item not found")
        return self._row(table, row)

    def _update_child(self, table, owner_key, item_id, values, allowed_fields):
        if table not in ENCRYPTED_FIELDS:
            raise ValueError("Unsupported project table")
        updates = {key: values[key] for key in allowed_fields if key in values}
        for field in ENCRYPTED_FIELDS[table]:
            if field in updates:
                updates[field] = self._encrypt(updates[field])
        updates["updated_at"] = self._now()
        assignments = ", ".join(f"{field} = ?" for field in updates)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ? AND owner_key = ?",
                (*updates.values(), item_id, owner_key),
            )
            if cursor.rowcount == 0:
                raise KeyError("Project item not found")
        return self._get_child(table, owner_key, item_id)

    def _delete_child(self, table, owner_key, item_id):
        if table not in ENCRYPTED_FIELDS:
            raise ValueError("Unsupported project table")
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE id = ? AND owner_key = ?",
                (item_id, owner_key),
            )
            if cursor.rowcount == 0:
                raise KeyError("Project item not found")
