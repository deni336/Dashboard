"""Encrypted, owner-scoped notes and code snippets for the personal dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime


MAX_ITEMS_PER_OWNER = 500
MAX_LIST_ITEMS = 200
MAX_CONTENT_BYTES = 64 * 1024
MAX_TITLE_LENGTH = 160
MAX_TAGS = 12
MAX_TAG_LENGTH = 32
MAX_QUERY_LENGTH = 120
MAX_PREVIEW_LENGTH = 240
ITEM_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
KINDS = {"note", "snippet"}
LANGUAGES = (
    "text",
    "markdown",
    "python",
    "javascript",
    "typescript",
    "powershell",
    "shell",
    "sql",
    "json",
    "yaml",
    "html",
    "css",
    "go",
    "rust",
    "java",
    "csharp",
    "cpp",
)
LANGUAGE_SET = set(LANGUAGES)
NOTE_LANGUAGES = {"text", "markdown"}
MUTABLE_FIELDS = {"kind", "title", "content", "language", "tags", "pinned"}


class VaultError(Exception):
    """Base knowledge-vault error safe for route translation."""


class ValidationError(VaultError):
    pass


class NotFoundError(VaultError):
    pass


class ConflictError(VaultError):
    def __init__(self, message="Knowledge item changed", *, current_version=None):
        super().__init__(message)
        self.current_version = current_version


class CapacityError(VaultError):
    pass


class StorageError(VaultError):
    pass


def _iso_timestamp(epoch):
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("version must be a positive integer")
    return value


def _title(value):
    if not isinstance(value, str):
        raise ValidationError("title must be a string")
    value = " ".join(value.split()).strip()
    if not value:
        raise ValidationError("title is required")
    if len(value) > MAX_TITLE_LENGTH:
        raise ValidationError(f"title must contain at most {MAX_TITLE_LENGTH} characters")
    return value


def _content(value):
    if not isinstance(value, str):
        raise ValidationError("content must be a string")
    if "\x00" in value:
        raise ValidationError("content contains an unsupported character")
    if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValidationError("content must contain at most 64 KiB of UTF-8 text")
    return value


def _tag(value, *, field="tag"):
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split()).strip()
    if not normalized:
        raise ValidationError(f"{field} must not be empty")
    if "," in normalized or any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValidationError(f"{field} must contain printable text without commas")
    if len(normalized) > MAX_TAG_LENGTH:
        raise ValidationError(f"{field} must contain at most {MAX_TAG_LENGTH} characters")
    return normalized


def _tags(value):
    if not isinstance(value, list):
        raise ValidationError("tags must be an array")
    if len(value) > MAX_TAGS:
        raise ValidationError(f"tags must contain at most {MAX_TAGS} entries")
    normalized = []
    seen = set()
    for entry in value:
        clean = _tag(entry, field="tag")
        key = clean.casefold()
        if key in seen:
            raise ValidationError("tags must be unique ignoring case")
        seen.add(key)
        normalized.append(clean)
    return normalized


def _validate_values(value):
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValidationError("kind must be note or snippet")
    language = value.get("language")
    if not isinstance(language, str) or language not in LANGUAGE_SET:
        raise ValidationError("language is unsupported")
    if kind == "note" and language not in NOTE_LANGUAGES:
        raise ValidationError("notes support only text or markdown")
    pinned = value.get("pinned")
    if not isinstance(pinned, bool):
        raise ValidationError("pinned must be true or false")
    return {
        "kind": kind,
        "title": _title(value.get("title")),
        "content": _content(value.get("content")),
        "language": language,
        "tags": _tags(value.get("tags")),
        "pinned": pinned,
    }


def validate_create(value):
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object")
    if set(value) != MUTABLE_FIELDS:
        missing = MUTABLE_FIELDS - set(value)
        unknown = set(value) - MUTABLE_FIELDS
        if missing:
            raise ValidationError(f"Request is missing field {sorted(missing)[0]}")
        raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
    return _validate_values(value)


def validate_patch(value):
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object")
    allowed = MUTABLE_FIELDS | {"version"}
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
    if "version" not in value:
        raise ValidationError("version is required")
    changes = {key: item for key, item in value.items() if key in MUTABLE_FIELDS}
    if not changes:
        raise ValidationError("At least one mutable field is required")
    return _version(value["version"]), changes


class KnowledgeVault:
    def __init__(self, dashboard_store, *, clock=None, id_factory=None):
        self.store = dashboard_store
        self.db_path = dashboard_store.db_path
        self.fernet = dashboard_store.fernet
        self.lookup_key = dashboard_store.lookup_key
        self.clock = clock or (lambda: datetime.now(UTC).timestamp())
        self.id_factory = id_factory or (lambda: secrets.token_hex(16))
        self._initialize()

    @contextmanager
    def _connect(self, *, immediate=False):
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    owner_key TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('note', 'snippet')),
                    pinned INTEGER NOT NULL CHECK (pinned IN (0, 1)),
                    version INTEGER NOT NULL CHECK (version >= 1),
                    payload_encrypted TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner_key, item_id)
                );
                CREATE INDEX IF NOT EXISTS knowledge_items_owner_updated_idx
                    ON knowledge_items(owner_key, pinned DESC, updated_at DESC);
                """
            )

    def _now(self):
        value = self.clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            value = value.astimezone(UTC).timestamp()
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("clock returned an invalid value")
        return value

    def _binding(self, owner_key, item_id):
        message = "\x00".join(
            ("knowledge-vault-payload-v1", str(owner_key), str(item_id))
        ).encode("utf-8", "strict")
        return hmac.new(self.lookup_key, message, hashlib.sha256).hexdigest()

    def _encrypt(self, owner_key, item_id, value):
        payload = {
            "schema_version": 1,
            "binding": self._binding(owner_key, item_id),
            "title": value["title"],
            "content": value["content"],
            "language": value["language"],
            "tags": value["tags"],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.fernet.encrypt(serialized).decode("ascii")

    def _decrypt(self, owner_key, row):
        try:
            raw = self.fernet.decrypt(str(row["payload_encrypted"]).encode("ascii"))
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "schema_version",
                "binding",
                "title",
                "content",
                "language",
                "tags",
            }:
                raise ValueError("invalid payload shape")
            if payload["schema_version"] != 1 or not hmac.compare_digest(
                str(payload["binding"]), self._binding(owner_key, row["item_id"])
            ):
                raise ValueError("invalid payload binding")
            value = _validate_values(
                {
                    "kind": row["kind"],
                    "title": payload["title"],
                    "content": payload["content"],
                    "language": payload["language"],
                    "tags": payload["tags"],
                    "pinned": bool(row["pinned"]),
                }
            )
        except Exception as exc:
            raise StorageError("Stored knowledge data could not be decrypted") from exc
        return value

    @staticmethod
    def _preview(content):
        return " ".join(content.split())[:MAX_PREVIEW_LENGTH]

    def _full(self, owner_key, row):
        value = self._decrypt(owner_key, row)
        return {
            "id": row["item_id"],
            "kind": row["kind"],
            "title": value["title"],
            "preview": self._preview(value["content"]),
            "language": value["language"],
            "tags": value["tags"],
            "pinned": bool(row["pinned"]),
            "version": row["version"],
            "created_at": _iso_timestamp(row["created_at"]),
            "updated_at": _iso_timestamp(row["updated_at"]),
            "content": value["content"],
        }

    @staticmethod
    def _summary(item):
        return {key: value for key, value in item.items() if key != "content"}

    @staticmethod
    def _validate_id(item_id):
        if not isinstance(item_id, str) or not ITEM_ID_PATTERN.fullmatch(item_id):
            raise NotFoundError("Knowledge item not found")

    def list(self, owner_key, *, kind="all", q="", tag="", pinned=None):
        if kind not in {"all", *KINDS}:
            raise ValidationError("kind filter is unsupported")
        if not isinstance(q, str) or len(q) > MAX_QUERY_LENGTH:
            raise ValidationError(f"q must contain at most {MAX_QUERY_LENGTH} characters")
        if not isinstance(tag, str) or len(tag) > MAX_TAG_LENGTH:
            raise ValidationError(f"tag must contain at most {MAX_TAG_LENGTH} characters")
        if pinned is not None and not isinstance(pinned, bool):
            raise ValidationError("pinned filter must be true or false")
        clean_tag = _tag(tag) if tag else ""
        query = unicodedata.normalize("NFKC", q).casefold()
        tag_key = clean_tag.casefold()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT owner_key, item_id, kind, pinned, version,
                          payload_encrypted, created_at, updated_at
                   FROM knowledge_items WHERE owner_key = ?
                   ORDER BY pinned DESC, updated_at DESC, item_id""",
                (owner_key,),
            ).fetchall()
        full_items = [self._full(owner_key, row) for row in rows]
        counts = {
            "total": len(full_items),
            "notes": sum(item["kind"] == "note" for item in full_items),
            "snippets": sum(item["kind"] == "snippet" for item in full_items),
            "pinned": sum(item["pinned"] for item in full_items),
        }
        tag_counts = {}
        for item in full_items:
            for name in item["tags"]:
                key = name.casefold()
                entry = tag_counts.setdefault(key, {"name": name, "count": 0})
                entry["count"] += 1
        filtered = []
        for item in full_items:
            if kind != "all" and item["kind"] != kind:
                continue
            if pinned is not None and item["pinned"] is not pinned:
                continue
            if tag_key and tag_key not in {name.casefold() for name in item["tags"]}:
                continue
            if query:
                haystack = unicodedata.normalize(
                    "NFKC",
                    "\n".join(
                        (item["title"], item["content"], *item["tags"])
                    ),
                ).casefold()
                if query not in haystack:
                    continue
            filtered.append(self._summary(item))
            if len(filtered) >= MAX_LIST_ITEMS:
                break
        return {
            "items": filtered,
            "counts": counts,
            "tags": sorted(tag_counts.values(), key=lambda entry: entry["name"].casefold()),
            "languages": list(LANGUAGES),
        }

    def get(self, owner_key, item_id):
        self._validate_id(item_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Knowledge item not found")
        return self._full(owner_key, row)

    def _insert(self, connection, owner_key, value, now):
        count = connection.execute(
            "SELECT COUNT(*) FROM knowledge_items WHERE owner_key = ?", (owner_key,)
        ).fetchone()[0]
        if count >= MAX_ITEMS_PER_OWNER:
            raise CapacityError("Knowledge vault item limit reached")
        item_id = self.id_factory()
        if not isinstance(item_id, str) or not ITEM_ID_PATTERN.fullmatch(item_id):
            raise StorageError("Knowledge item identity could not be created")
        encrypted = self._encrypt(owner_key, item_id, value)
        try:
            connection.execute(
                """INSERT INTO knowledge_items
                       (owner_key, item_id, kind, pinned, version,
                        payload_encrypted, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
                (
                    owner_key,
                    item_id,
                    value["kind"],
                    int(value["pinned"]),
                    encrypted,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageError("Knowledge item identity could not be created") from exc
        return item_id

    def create(self, owner_key, payload):
        value = validate_create(payload)
        now = self._now()
        with self._connect(immediate=True) as connection:
            item_id = self._insert(connection, owner_key, value, now)
        return self.get(owner_key, item_id)

    def update(self, owner_key, item_id, payload):
        self._validate_id(item_id)
        expected_version, changes = validate_patch(payload)
        now = self._now()
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Knowledge item not found")
            if row["version"] != expected_version:
                raise ConflictError(current_version=row["version"])
            value = self._decrypt(owner_key, row)
            value.update(changes)
            value = _validate_values(value)
            encrypted = self._encrypt(owner_key, item_id, value)
            updated = connection.execute(
                """UPDATE knowledge_items SET kind = ?, pinned = ?, version = version + 1,
                          payload_encrypted = ?, updated_at = ?
                   WHERE owner_key = ? AND item_id = ? AND version = ?""",
                (
                    value["kind"],
                    int(value["pinned"]),
                    encrypted,
                    now,
                    owner_key,
                    item_id,
                    expected_version,
                ),
            )
            if updated.rowcount != 1:
                raise ConflictError(current_version=expected_version + 1)
            result_row = connection.execute(
                "SELECT * FROM knowledge_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            result = self._full(owner_key, result_row)
        return result

    def delete(self, owner_key, item_id, version):
        self._validate_id(item_id)
        expected_version = _version(version)
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                """SELECT version FROM knowledge_items
                   WHERE owner_key = ? AND item_id = ?""",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Knowledge item not found")
            if row["version"] != expected_version:
                raise ConflictError(current_version=row["version"])
            deleted = connection.execute(
                """DELETE FROM knowledge_items
                   WHERE owner_key = ? AND item_id = ? AND version = ?""",
                (owner_key, item_id, expected_version),
            )
            if deleted.rowcount != 1:
                raise ConflictError(current_version=expected_version + 1)

    def duplicate(self, owner_key, item_id):
        self._validate_id(item_id)
        now = self._now()
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Knowledge item not found")
            value = self._decrypt(owner_key, row)
            new_id = self._insert(connection, owner_key, value, now)
        return self.get(owner_key, new_id)
