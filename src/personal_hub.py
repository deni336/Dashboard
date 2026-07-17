"""Encrypted reminders, countdowns, habits, and bookmarks for one owner."""

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
from datetime import UTC, date, datetime
from urllib.parse import urlsplit


MAX_ITEMS_PER_OWNER = 250
MAX_TITLE_LENGTH = 120
MAX_NOTE_LENGTH = 1000
MAX_URL_LENGTH = 2048
MAX_CHECKINS = 90
CHECKIN_WINDOW_DAYS = 14
ITEM_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KINDS = {"reminder", "countdown", "habit", "bookmark"}
CADENCES = {"daily", "weekdays", "weekly"}
COMMON_FIELDS = {"title", "note"}
KIND_FIELDS = {
    "reminder": {"due_at", "completed"},
    "countdown": {"target_at"},
    "habit": {"cadence", "checkins"},
    "bookmark": {"url"},
}
PATCH_FIELDS = {
    "reminder": COMMON_FIELDS | {"due_at", "completed"},
    "countdown": COMMON_FIELDS | {"target_at"},
    "habit": COMMON_FIELDS | {"cadence"},
    "bookmark": COMMON_FIELDS | {"url"},
}


class HubError(Exception):
    """Base error that may be translated by the HTTP boundary."""


class ValidationError(HubError):
    pass


class NotFoundError(HubError):
    pass


class ConflictError(HubError):
    def __init__(self, message="Personal Hub item changed", *, current_version=None):
        super().__init__(message)
        self.current_version = current_version


class CapacityError(HubError):
    pass


class StorageError(HubError):
    pass


def _iso_timestamp(epoch):
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _has_control(value):
    return any(unicodedata.category(character) == "Cc" for character in value)


def _version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError("version must be a positive integer")
    return value


def _title(value):
    if not isinstance(value, str):
        raise ValidationError("title must be a string")
    if _has_control(value):
        raise ValidationError("title must not contain control characters")
    value = " ".join(value.split()).strip()
    if not value:
        raise ValidationError("title is required")
    if len(value) > MAX_TITLE_LENGTH:
        raise ValidationError(f"title must contain at most {MAX_TITLE_LENGTH} characters")
    return value


def _note(value):
    if not isinstance(value, str):
        raise ValidationError("note must be a string")
    if _has_control(value):
        raise ValidationError("note must not contain control characters")
    if len(value) > MAX_NOTE_LENGTH:
        raise ValidationError(f"note must contain at most {MAX_NOTE_LENGTH} characters")
    return value


def _rfc3339(value, field):
    if not isinstance(value, str) or not RFC3339_PATTERN.fullmatch(value):
        raise ValidationError(f"{field} must be an RFC3339 timestamp with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be an RFC3339 timestamp with a timezone"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{field} must be an RFC3339 timestamp with a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _url(value):
    if not isinstance(value, str):
        raise ValidationError("url must be a string")
    if not value or len(value) > MAX_URL_LENGTH:
        raise ValidationError(f"url must contain between 1 and {MAX_URL_LENGTH} characters")
    if _has_control(value) or "\\" in value or any(character.isspace() for character in value):
        raise ValidationError("url must be a valid HTTPS URL")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        # Accessing port also validates malformed and out-of-range ports.
        parsed.port
    except ValueError as exc:
        raise ValidationError("url must be a valid HTTPS URL") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValidationError("url must be HTTPS and must not contain credentials")
    return value


def _cadence(value):
    if not isinstance(value, str) or value not in CADENCES:
        raise ValidationError("cadence must be daily, weekdays, or weekly")
    return value


def _completed(value):
    if not isinstance(value, bool):
        raise ValidationError("completed must be true or false")
    return value


def _checkin_date(value):
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise ValidationError("date must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValidationError("date must use YYYY-MM-DD")
    return parsed


def _stored_checkins(value):
    if not isinstance(value, list) or len(value) > MAX_CHECKINS:
        raise ValidationError(f"checkins must be an array of at most {MAX_CHECKINS} dates")
    normalized = []
    seen = set()
    for entry in value:
        clean = _checkin_date(entry).isoformat()
        if clean in seen:
            raise ValidationError("checkins must contain unique dates")
        seen.add(clean)
        normalized.append(clean)
    if normalized != sorted(normalized):
        raise ValidationError("checkins must be sorted")
    return normalized


def _validate_values(kind, value, *, creating=False):
    if kind not in KINDS:
        raise ValidationError("kind must be reminder, countdown, habit, or bookmark")
    expected = COMMON_FIELDS | KIND_FIELDS[kind]
    if set(value) != expected:
        missing = expected - set(value)
        unknown = set(value) - expected
        if missing:
            raise ValidationError(f"Request is missing field {sorted(missing)[0]}")
        raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
    result = {"title": _title(value["title"]), "note": _note(value["note"])}
    if kind == "reminder":
        result["due_at"] = _rfc3339(value["due_at"], "due_at")
        result["completed"] = _completed(value["completed"])
        if creating and result["completed"] is not False:
            raise ValidationError("completed must be false when a reminder is created")
    elif kind == "countdown":
        result["target_at"] = _rfc3339(value["target_at"], "target_at")
    elif kind == "habit":
        result["cadence"] = _cadence(value["cadence"])
        result["checkins"] = _stored_checkins(value["checkins"])
        if creating and result["checkins"]:
            raise ValidationError("checkins must be empty when a habit is created")
    else:
        result["url"] = _url(value["url"])
    return result


def validate_create(payload):
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    if "kind" not in payload:
        raise ValidationError("Request is missing field kind")
    kind = payload["kind"]
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValidationError("kind must be reminder, countdown, habit, or bookmark")
    value = {key: entry for key, entry in payload.items() if key != "kind"}
    return kind, _validate_values(kind, value, creating=True)


def validate_patch(payload):
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    if "kind" in payload:
        raise ValidationError("kind is immutable")
    if "version" not in payload:
        raise ValidationError("version is required")
    expected_version = _version(payload["version"])
    changes = {key: value for key, value in payload.items() if key != "version"}
    if not changes:
        raise ValidationError("At least one mutable field is required")
    all_fields = set().union(*PATCH_FIELDS.values())
    unknown = set(changes) - all_fields
    if unknown:
        raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
    return expected_version, changes


class PersonalHub:
    """Encrypted owner-scoped storage over a shared PersonalDashboardStore."""

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
                CREATE TABLE IF NOT EXISTS personal_hub_items (
                    owner_key TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (
                        kind IN ('reminder', 'countdown', 'habit', 'bookmark')
                    ),
                    version INTEGER NOT NULL CHECK (version >= 1),
                    payload_encrypted TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(owner_key, item_id)
                );
                CREATE INDEX IF NOT EXISTS personal_hub_owner_updated_idx
                    ON personal_hub_items(owner_key, updated_at DESC, item_id);
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
            ("personal-hub-payload-v1", str(owner_key), str(item_id))
        ).encode("utf-8", "strict")
        return hmac.new(self.lookup_key, message, hashlib.sha256).hexdigest()

    def _encrypt(self, owner_key, item_id, value):
        payload = {
            "schema_version": 1,
            "binding": self._binding(owner_key, item_id),
            **value,
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
            kind = str(row["kind"])
            expected = {"schema_version", "binding"} | COMMON_FIELDS | KIND_FIELDS[kind]
            if not isinstance(payload, dict) or set(payload) != expected:
                raise ValueError("invalid payload shape")
            if payload["schema_version"] != 1 or not hmac.compare_digest(
                str(payload["binding"]), self._binding(owner_key, row["item_id"])
            ):
                raise ValueError("invalid payload binding")
            value = {
                key: entry
                for key, entry in payload.items()
                if key not in {"schema_version", "binding"}
            }
            return _validate_values(kind, value)
        except Exception as exc:
            raise StorageError("Stored Personal Hub data could not be decrypted") from exc

    @staticmethod
    def _validate_id(item_id):
        if not isinstance(item_id, str) or not ITEM_ID_PATTERN.fullmatch(item_id):
            raise NotFoundError("Personal Hub item not found")

    def _full(self, owner_key, row):
        value = self._decrypt(owner_key, row)
        return {
            "id": row["item_id"],
            "kind": row["kind"],
            "title": value.pop("title"),
            "note": value.pop("note"),
            **value,
            "version": row["version"],
            "created_at": _iso_timestamp(row["created_at"]),
            "updated_at": _iso_timestamp(row["updated_at"]),
        }

    @staticmethod
    def _summary(item):
        return {key: value for key, value in item.items() if key != "note"}

    def list(self, owner_key):
        now = self._now()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT owner_key, item_id, kind, version, payload_encrypted,
                          created_at, updated_at
                   FROM personal_hub_items WHERE owner_key = ?
                   ORDER BY updated_at DESC, item_id""",
                (owner_key,),
            ).fetchall()
        items = [self._full(owner_key, row) for row in rows]
        return {
            "generated_at": _iso_timestamp(now),
            "counts": {
                "total": len(items),
                "reminders": sum(item["kind"] == "reminder" for item in items),
                "countdowns": sum(item["kind"] == "countdown" for item in items),
                "habits": sum(item["kind"] == "habit" for item in items),
                "bookmarks": sum(item["kind"] == "bookmark" for item in items),
            },
            "items": [self._summary(item) for item in items],
        }

    def get(self, owner_key, item_id):
        self._validate_id(item_id)
        with self._connect() as connection:
            row = connection.execute(
                """SELECT owner_key, item_id, kind, version, payload_encrypted,
                          created_at, updated_at
                   FROM personal_hub_items
                   WHERE owner_key = ? AND item_id = ?""",
                (owner_key, item_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Personal Hub item not found")
        return self._full(owner_key, row)

    def create(self, owner_key, payload):
        kind, value = validate_create(payload)
        now = self._now()
        with self._connect(immediate=True) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM personal_hub_items WHERE owner_key = ?",
                (owner_key,),
            ).fetchone()[0]
            if count >= MAX_ITEMS_PER_OWNER:
                raise CapacityError("Personal Hub item limit reached")
            item_id = self.id_factory()
            if not isinstance(item_id, str) or not ITEM_ID_PATTERN.fullmatch(item_id):
                raise StorageError("Personal Hub item identity could not be created")
            encrypted = self._encrypt(owner_key, item_id, value)
            try:
                connection.execute(
                    """INSERT INTO personal_hub_items
                           (owner_key, item_id, kind, version, payload_encrypted,
                            created_at, updated_at)
                       VALUES (?, ?, ?, 1, ?, ?, ?)""",
                    (owner_key, item_id, kind, encrypted, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise StorageError("Personal Hub item identity could not be created") from exc
            row = connection.execute(
                "SELECT * FROM personal_hub_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            result = self._full(owner_key, row)
        return result

    def update(self, owner_key, item_id, payload):
        self._validate_id(item_id)
        expected_version, changes = validate_patch(payload)
        now = self._now()
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM personal_hub_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Personal Hub item not found")
            if row["version"] != expected_version:
                raise ConflictError(current_version=row["version"])
            kind = row["kind"]
            unsupported = set(changes) - PATCH_FIELDS[kind]
            if unsupported:
                raise ValidationError(
                    f"Request contains unsupported field {sorted(unsupported)[0]}"
                )
            value = self._decrypt(owner_key, row)
            value.update(changes)
            value = _validate_values(kind, value)
            encrypted = self._encrypt(owner_key, item_id, value)
            updated = connection.execute(
                """UPDATE personal_hub_items
                   SET version = version + 1, payload_encrypted = ?, updated_at = ?
                   WHERE owner_key = ? AND item_id = ? AND version = ?""",
                (encrypted, now, owner_key, item_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError(current_version=expected_version + 1)
            new_row = connection.execute(
                "SELECT * FROM personal_hub_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            result = self._full(owner_key, new_row)
        return result

    def delete(self, owner_key, item_id, version):
        self._validate_id(item_id)
        expected_version = _version(version)
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                """SELECT version FROM personal_hub_items
                   WHERE owner_key = ? AND item_id = ?""",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Personal Hub item not found")
            if row["version"] != expected_version:
                raise ConflictError(current_version=row["version"])
            deleted = connection.execute(
                """DELETE FROM personal_hub_items
                   WHERE owner_key = ? AND item_id = ? AND version = ?""",
                (owner_key, item_id, expected_version),
            )
            if deleted.rowcount != 1:
                raise ConflictError(current_version=expected_version + 1)

    def toggle_checkin(self, owner_key, item_id, payload):
        self._validate_id(item_id)
        if not isinstance(payload, dict):
            raise ValidationError("Request body must be a JSON object")
        if set(payload) != {"version", "date"}:
            missing = {"version", "date"} - set(payload)
            unknown = set(payload) - {"version", "date"}
            if missing:
                raise ValidationError(f"Request is missing field {sorted(missing)[0]}")
            raise ValidationError(f"Request contains unsupported field {sorted(unknown)[0]}")
        expected_version = _version(payload["version"])
        checkin = _checkin_date(payload["date"])
        now = self._now()
        today = datetime.fromtimestamp(now, UTC).date()
        if abs((checkin - today).days) > CHECKIN_WINDOW_DAYS:
            raise ValidationError(
                f"date must be within {CHECKIN_WINDOW_DAYS} days of today"
            )
        with self._connect(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM personal_hub_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Personal Hub item not found")
            if row["version"] != expected_version:
                raise ConflictError(current_version=row["version"])
            if row["kind"] != "habit":
                raise ValidationError("check-ins are supported only for habits")
            value = self._decrypt(owner_key, row)
            checkins = set(value["checkins"])
            checkin_text = checkin.isoformat()
            if checkin_text in checkins:
                checkins.remove(checkin_text)
            else:
                checkins.add(checkin_text)
            value["checkins"] = sorted(checkins)[-MAX_CHECKINS:]
            value = _validate_values("habit", value)
            encrypted = self._encrypt(owner_key, item_id, value)
            updated = connection.execute(
                """UPDATE personal_hub_items
                   SET version = version + 1, payload_encrypted = ?, updated_at = ?
                   WHERE owner_key = ? AND item_id = ? AND version = ?""",
                (encrypted, now, owner_key, item_id, expected_version),
            )
            if updated.rowcount != 1:
                raise ConflictError(current_version=expected_version + 1)
            new_row = connection.execute(
                "SELECT * FROM personal_hub_items WHERE owner_key = ? AND item_id = ?",
                (owner_key, item_id),
            ).fetchone()
            result = self._full(owner_key, new_row)
        return result
